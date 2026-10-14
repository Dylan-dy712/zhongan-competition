"""Isolated competition account allocator; shares existing revocable sessions."""
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg.rows import dict_row

from services.api.app import accounts

CAPACITY = 50
LOCK_NAME = 'zhongan-judge-demo-v1'
ROOT = Path(__file__).resolve().parent
app = FastAPI(title='Competition judge entry', docs_url=None, redoc_url=None, openapi_url=None)


class Visitor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    visitor_id: str = Field(pattern=r'^[0-9a-f]{64}$')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def seed_pool(conn):
    """Idempotent provisioning. Never claims or converts an existing user account."""
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK_NAME,))
        conn.execute('''CREATE TABLE IF NOT EXISTS judge_demo_slots (
            slot integer PRIMARY KEY CHECK (slot BETWEEN 1 AND 50),
            actor_id uuid UNIQUE NOT NULL REFERENCES user_accounts(actor_id),
            visitor_sha256 char(64) UNIQUE,
            assigned_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((visitor_sha256 IS NULL) = (assigned_at IS NULL)))''')
        existing = {row['slot'] for row in conn.execute('SELECT slot FROM judge_demo_slots').fetchall()}
        for slot in range(1, CAPACITY + 1):
            if slot in existing:
                continue
            while True:
                username = '199' + str(secrets.randbelow(100_000_000)).zfill(8)
                if not conn.execute('SELECT 1 FROM user_accounts WHERE username=%s', (username,)).fetchone():
                    break
            result = accounts.register(conn, accounts.Registration(
                username=username, password=secrets.token_urlsafe(48),
                display_name=f'评委体验 {slot:02d}', care_consent=True))
            user = conn.execute('SELECT actor_id,subject_id FROM user_accounts WHERE username=%s', (username,)).fetchone()
            # Registration's setup token is never shared; each visitor gets a fresh session.
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE token_sha256=%s',
                         (digest(result['access_token']),))
            conn.execute('''INSERT INTO account_members(actor_id,subject_id,name,relationship,profile_completed)
                VALUES (%s,%s,%s,'self',true)''', (user['actor_id'], user['subject_id'], f'体验成员 {slot:02d}'))
            conn.execute('INSERT INTO judge_demo_slots(slot,actor_id) VALUES (%s,%s)', (slot, user['actor_id']))
    return CAPACITY


def allocate(conn, visitor_id):
    visitor_hash = digest(visitor_id)
    with conn.transaction():
        # One short transaction serializes allocation and repeat scans, including a full pool.
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (LOCK_NAME,))
        row = conn.execute('SELECT slot,actor_id FROM judge_demo_slots WHERE visitor_sha256=%s',
                           (visitor_hash,)).fetchone()
        if row is None:
            row = conn.execute('SELECT slot,actor_id FROM judge_demo_slots WHERE visitor_sha256 IS NULL ORDER BY slot LIMIT 1 FOR UPDATE').fetchone()
            if row is None:
                raise HTTPException(409, '50 个体验账号已全部分配，请联系现场工作人员。')
            conn.execute('UPDATE judge_demo_slots SET visitor_sha256=%s,assigned_at=now() WHERE slot=%s',
                         (visitor_hash, row['slot']))
        if not conn.execute('SELECT 1 FROM actors WHERE actor_id=%s AND active=true', (row['actor_id'],)).fetchone():
            raise HTTPException(403, '该体验账号已停用，请联系现场工作人员。')
        result = accounts.session(conn, row['actor_id'])
        return {**result, 'slot': row['slot']}


def validate_entry(authorization):
    expected = os.getenv('ZHONGAN_JUDGE_ENTRY_KEY', '')
    if len(expected) < 32:
        raise HTTPException(503, '体验入口暂未开放。')
    if not hmac.compare_digest((authorization or '').encode('utf-8'), ('Demo ' + expected).encode('utf-8')):
        raise HTTPException(403, '体验链接无效，请重新扫描现场二维码。')


@app.get('/judge/health')
def health():
    return {'status': 'ok', 'capacity': CAPACITY}


@app.get('/judge/')
def entry():
    return FileResponse(ROOT / 'index.html', headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})


@app.get('/judge/entry.js')
def entry_script():
    return FileResponse(ROOT / 'entry.js', media_type='text/javascript', headers={'Cache-Control': 'no-store'})


@app.post('/judge/session')
def judge_session(body: Visitor, response: Response, authorization: str | None = Header(default=None)):
    validate_entry(authorization)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    try:
        with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'], row_factory=dict_row, connect_timeout=5) as conn:
            return allocate(conn, body.visitor_id)
    except psycopg.Error:
        raise HTTPException(503, '暂时连接不上体验服务，请稍后重试。') from None
    except KeyError:
        raise HTTPException(503, '体验服务暂未配置。') from None


if __name__ == '__main__':
    with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'], row_factory=dict_row) as connection:
        seed_pool(connection)
    print('Judge demo pool ready: 50 isolated accounts. No credentials emitted.')
