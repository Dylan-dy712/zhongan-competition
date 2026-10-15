"""Prepare server-local invitation and accounts; never emit secrets."""
import importlib.util
import json
import os
import secrets
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent
CONFIG = Path('/home/ubuntu/.config/zhongan/judge-demo.env')
spec = importlib.util.spec_from_file_location('judge_allocator', ROOT / 'app.py')
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)
if not CONFIG.exists():
    fd = os.open(CONFIG, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('ZHONGAN_JUDGE_ENTRY_KEY=' + secrets.token_urlsafe(32) + '\n')
CONFIG.chmod(0o600)
with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'], row_factory=dict_row) as conn:
    judge.seed_pool(conn)
    counts = conn.execute('SELECT count(*) AS total,count(visitor_sha256) AS assigned FROM judge_demo_slots').fetchone()
print(json.dumps({'capacity': counts['total'], 'assigned': counts['assigned'], 'available': counts['total'] - counts['assigned']}))
