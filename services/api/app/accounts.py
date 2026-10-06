"""Password accounts and revocable, hashed opaque sessions."""
import hashlib
import json
import hmac
import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, field_validator

from .repository import token_digest
from .contracts.core import Contract


class Credentials(Contract):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(min_length=10, max_length=128)

    @field_validator('username')
    @classmethod
    def normalize(cls, value):
        return value.lower()


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=40)
    care_consent: bool

    @field_validator('display_name')
    @classmethod
    def name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Name required')
        return value


class AccountUser(Contract):
    username: str
    display_name: str


class SessionResponse(Contract):
    schema_version: Literal['account-v1'] = 'account-v1'
    access_token: str
    token_type: Literal['bearer'] = 'bearer'
    expires_at: datetime
    user: AccountUser


class ProfileResponse(Contract):
    schema_version: Literal['account-v1'] = 'account-v1'
    user: AccountUser | None


class ConsentResponse(Contract):
    schema_version: Literal['account-consent-v1'] = 'account-consent-v1'
    subject_id: UUID
    consent_id: UUID | None
    version: int
    status: Literal['active','revoked','expired','not_granted']
    notice_version: str
    purpose: Literal['case_guidance']


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def verify_password(password, encoded):
    try:
        scheme, salt, _ = encoded.split('$')
        return scheme == 'scrypt' and hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = hash_password('dummy-password')


def rate_limit(conn, key, limit):
    # A separate committed transaction preserves failed attempts on HTTP errors.
    with conn.transaction():
        row = conn.execute("""INSERT INTO auth_attempts(attempt_key,attempts) VALUES (%s,1)
            ON CONFLICT(attempt_key) DO UPDATE SET
            attempts=CASE WHEN auth_attempts.window_started_at < now()-interval '15 minutes'
                THEN 1 ELSE auth_attempts.attempts+1 END,
            window_started_at=CASE WHEN auth_attempts.window_started_at < now()-interval '15 minutes'
                THEN now() ELSE auth_attempts.window_started_at END RETURNING attempts""",
            (token_digest(key),)).fetchone()
    conn.commit()
    if row['attempts'] > limit:
        raise HTTPException(429, '尝试次数过多，请 15 分钟后重试。')


def session(conn, actor_id):
    token = secrets.token_urlsafe(48)
    row = conn.execute("""INSERT INTO auth_sessions(token_sha256,actor_id,expires_at)
        VALUES (%s,%s,now()+interval '12 hours') RETURNING expires_at""",
        (token_digest(token), actor_id)).fetchone()
    user = conn.execute('SELECT username,display_name FROM user_accounts WHERE actor_id=%s', (actor_id,)).fetchone()
    return {'access_token': token, 'token_type': 'bearer', 'expires_at': row['expires_at'], 'user': user}


def register(conn, body):
    password_hash = hash_password(body.password)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('register:'+body.username,))
        if conn.execute('SELECT 1 FROM user_accounts WHERE username=%s', (body.username,)).fetchone():
            raise HTTPException(409, '该用户名已被注册，请换一个或直接登录。')
        actor, subject, consent = uuid4(), uuid4(), uuid4()
        # Account actors have no usable legacy token; only expiring sessions authenticate them.
        conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)',
                     (actor, token_digest(secrets.token_urlsafe(48))))
        conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)', (actor, subject))
        conn.execute('INSERT INTO user_accounts(actor_id,subject_id,username,display_name,password_hash) VALUES (%s,%s,%s,%s,%s)',
                     (actor, subject, body.username, body.display_name, password_hash))
        if body.care_consent:
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'account-care-v1',1)", (consent, subject))
            conn.execute("""INSERT INTO consent_purposes(consent_id,purpose,status,granted_at)
                VALUES (%s,'case_guidance','active',now())""", (consent,))
        return session(conn, actor)


class ConsentChange(Contract):
    confirmation: bool
    expected_version: int = Field(ge=0)


def care_consent(conn, actor_id):
    owner = conn.execute('SELECT subject_id FROM user_accounts WHERE actor_id=%s', (actor_id,)).fetchone()
    if not owner:
        raise HTTPException(403, '此功能仅适用于注册账号。')
    row = conn.execute("""SELECT c.consent_id,c.version,c.notice_version,
        CASE WHEN p.status='active' AND p.expires_at IS NOT NULL AND p.expires_at<=clock_timestamp()
             THEN 'expired' ELSE p.status END AS status FROM consents c
        JOIN consent_purposes p USING(consent_id) WHERE c.subject_id=%s AND p.purpose='case_guidance'
        ORDER BY c.created_at DESC LIMIT 1""", (owner['subject_id'],)).fetchone()
    return {'subject_id': owner['subject_id'], 'version': row['version'] if row else 0,
            'status': row['status'] if row else 'not_granted', 'consent_id': row['consent_id'] if row else None,
            'notice_version': 'account-care-v1', 'purpose': 'case_guidance'}


def change_consent(conn, actor_id, body, idempotency_key):
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('consent:'+str(actor_id),))
        digest=token_digest(json.dumps(body.model_dump(),sort_keys=True))
        previous=conn.execute('SELECT request_hash,response FROM account_consent_operations WHERE actor_id=%s AND idempotency_key=%s', (actor_id,idempotency_key)).fetchone()
        if previous:
            if previous['request_hash']!=digest:
                raise HTTPException(409, '同一请求标识不能用于不同的授权操作。')
            return previous['response']
        current = care_consent(conn, actor_id)
        target = 'active' if body.confirmation else 'revoked'
        if current['version'] != body.expected_version:
            raise HTTPException(409, '授权版本已更新，请刷新后重试。')
        if current['status']==target:
            conn.execute('INSERT INTO account_consent_operations VALUES (%s,%s,%s,%s::jsonb,now())', (actor_id,idempotency_key,digest,json.dumps(current,default=str)))
            return current
        if current['consent_id']:
            conn.execute('UPDATE consents SET version=version+1 WHERE consent_id=%s', (current['consent_id'],))
            conn.execute("""UPDATE consent_purposes SET status=%s,
                granted_at=CASE WHEN %s THEN now() ELSE granted_at END,
                revoked_at=CASE WHEN %s THEN NULL ELSE now() END,
                expires_at=CASE WHEN %s THEN NULL ELSE expires_at END WHERE consent_id=%s AND purpose='case_guidance'""",
                (target, body.confirmation, body.confirmation, body.confirmation, current['consent_id']))
        elif body.confirmation:
            consent_id=uuid4()
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'account-care-v1',1)", (consent_id,current['subject_id']))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (consent_id,))
        result=care_consent(conn, actor_id)
        conn.execute('INSERT INTO account_consent_operations VALUES (%s,%s,%s,%s::jsonb,now())', (actor_id,idempotency_key,digest,json.dumps(result,default=str)))
        return result


def login(conn, body):
    rate_limit(conn, 'login:'+body.username, 10)
    user = conn.execute("""SELECT u.* FROM user_accounts u JOIN actors a USING(actor_id)
        WHERE username=%s AND a.active=true""", (body.username,)).fetchone()
    # Run the same expensive hash for unknown users.
    encoded = user['password_hash'] if user else _DUMMY_PASSWORD_HASH
    valid = verify_password(body.password, encoded)
    if not user or not valid:
        raise HTTPException(401, '用户名或密码不正确。')
    with conn.transaction():
        return session(conn, user['actor_id'])
