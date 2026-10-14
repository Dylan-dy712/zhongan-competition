"""Isolated competition account allocator; shares existing revocable sessions."""
import hashlib
import hmac
import os
import secrets
import json
import re
from pathlib import Path
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg.rows import dict_row

from services.api.app import accounts
from services.api.app.repository import actor_for_token

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


def require_judge(conn, authorization):
    if not authorization or not authorization.startswith('Bearer ') or len(authorization)>4096:
        raise HTTPException(401, '请先进入评委体验账号。')
    actor=actor_for_token(conn,authorization.removeprefix('Bearer '))
    if actor is None:
        raise HTTPException(401, '登录已失效，请重新扫描体验二维码。')
    if not conn.execute('SELECT 1 FROM judge_demo_slots WHERE actor_id=%s',(actor,)).fetchone():
        raise HTTPException(403, '示例资料仅供评委体验账号使用。')
    return actor


def read_sample_manifest(directory):
    try:
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('data_origin')!='official_deidentified':raise ValueError('Invalid sample origin')
        for key in ('sample_id','version'):
            if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',manifest[key]):raise ValueError('Invalid identity')
        documents=manifest['documents']
        if not 1<=len(documents)<=10 or manifest['file_count']!=len(documents):raise ValueError('Invalid count')
        if len({item['id'] for item in documents})!=len(documents):raise ValueError('Duplicate document')
        for item in documents:
            if not re.fullmatch(r'[a-z0-9-]{1,64}\.pdf',item['file']):raise ValueError('Invalid file')
            path=directory/item['file']
            if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():raise ValueError('Escaped file')
            if item['media_type']!='application/pdf' or not 0<path.stat().st_size<=10*1024*1024:raise ValueError('Invalid media')
            if not re.fullmatch(r'[0-9a-f]{64}',item['sha256']) or not 1<=item['page_count']<=10:raise ValueError('Invalid metadata')
            if not isinstance(item['name'],str) or not 1<=len(item['name'])<=200:raise ValueError('Invalid name')
        if manifest['page_count']!=sum(item['page_count'] for item in documents):raise ValueError('Invalid pages')
        return directory,manifest
    except (OSError,ValueError,KeyError,TypeError):
        raise HTTPException(503, '示例资料暂未准备好，请稍后再试。') from None


def sample_manifest(version=None):
    directory=Path(os.getenv('ZHONGAN_JUDGE_SAMPLE_ROOT','/home/ubuntu/.config/zhongan/judge-sample')).resolve()
    directory,manifest=read_sample_manifest(directory)
    if version is None or version==manifest['version']:return directory,manifest
    if not isinstance(version,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',version):
        raise HTTPException(404,'示例资料版本不存在。')
    # Reviewed versions are immutable private siblings; preserve selections during updates.
    previous=directory.parent/(manifest['sample_id']+'-'+version)
    if previous.is_symlink() or previous.resolve().parent!=directory.parent:
        raise HTTPException(404,'示例资料版本不存在。')
    old_directory,old_manifest=read_sample_manifest(previous)
    if old_manifest['sample_id']!=manifest['sample_id'] or old_manifest['version']!=version:
        raise HTTPException(404,'示例资料版本不存在。')
    return old_directory,old_manifest


def sample_info():
    _,manifest=sample_manifest()
    return {key:manifest[key] for key in ('sample_id','version','title','summary','notice','data_origin','file_count','page_count','claim_info')} | {
        'documents':[{key:item[key] for key in ('id','name','page_count','document_type','sha256')} for item in manifest['documents']]}


def sample_document(document_id,version=None):
    directory,manifest=sample_manifest(version)
    item=next((item for item in manifest['documents'] if item['id']==document_id),None)
    if item is None:raise HTTPException(404,'示例资料不存在。')
    path=directory/item['file']
    with path.open('rb') as handle:
        if handle.read(5)!=b'%PDF-':raise HTTPException(503,'示例资料校验未通过。')
        handle.seek(0)
        if hashlib.file_digest(handle,'sha256').hexdigest()!=item['sha256']:
            raise HTTPException(503,'示例资料校验未通过。')
    return FileResponse(path,media_type=item['media_type'],filename=item['name'],headers={
        'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow','X-Content-Type-Options':'nosniff'})


def judge_upload_allowed(conn,actor_id,body):
    """Enable exactly the reviewed library for judge uploads; other imports stay closed."""
    context=body.user_context or {}
    if body.data_origin!='official_deidentified' or context.get('judge_demo') is not True:
        return False
    source_ref=getattr(body,'source_ref',None)
    if source_ref is None and getattr(body,'case_id',None):
        row=conn.execute('SELECT source_ref FROM cases WHERE case_id=%s',(body.case_id,)).fetchone()
        source_ref=row['source_ref'] if row else None
    if not source_ref or not source_ref.startswith('judge-upload-sample:'):return False
    if not conn.execute("SELECT to_regclass('judge_demo_slots') AS name").fetchone()['name']:return False
    if not conn.execute('SELECT 1 FROM judge_demo_slots WHERE actor_id=%s',(actor_id,)).fetchone():return False
    _,manifest=sample_manifest(context.get('sample_version'))
    return (source_ref=='judge-upload-sample:'+manifest['sample_id'] and
            context.get('sample_id')==manifest['sample_id'] and context.get('sample_version')==manifest['version'] and
            context.get('notice')==manifest['notice'])


def verify_sample_upload(conn,actor_id,case,source_hash):
    if case.data_origin!='official_deidentified' or not (case.user_context or {}).get('judge_demo'):return
    if not judge_upload_allowed(conn,actor_id,case):raise HTTPException(403,'当前示例资料授权已变更。')
    _,manifest=sample_manifest(case.user_context.get('sample_version'))
    if source_hash not in {item['sha256'] for item in manifest['documents']}:
        raise HTTPException(422,'请使用当前示例病例提供的文件；其他资料请在新的申请中上传。')


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


@app.get('/judge/sample')
def judge_sample_info(response: Response, authorization: str | None = Header(default=None)):
    response.headers['Cache-Control']='no-store'
    try:
        with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'],row_factory=dict_row,connect_timeout=5) as conn:
            require_judge(conn,authorization)
            return sample_info()
    except (psycopg.Error,KeyError):
        raise HTTPException(503,'示例资料服务暂时不可用。') from None


@app.get('/judge/sample/files/{document_id}')
def judge_sample_file(document_id: str, version: str | None = None, authorization: str | None = Header(default=None)):
    try:
        with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'],row_factory=dict_row,connect_timeout=5) as conn:
            actor=require_judge(conn,authorization)
            if accounts.care_consent(conn,actor)['status']!='active':
                raise HTTPException(403,'请先确认资料用途授权，再选择示例资料。')
            return sample_document(document_id,version)
    except (psycopg.Error,KeyError):
        raise HTTPException(503,'示例资料服务暂时不可用。') from None


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
