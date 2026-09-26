"""Apply versioned SQL migrations transactionally to ZHONGAN_DATABASE_URL."""
import hashlib
import os
from pathlib import Path

from services.api.app.repository import connect


def main():
    root=Path(__file__).resolve().parents[1]/'services'/'api'/'sql'
    with connect(os.environ['ZHONGAN_DATABASE_URL']) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('zhongan:migrations',0))")
        conn.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
            name text PRIMARY KEY, sha256 char(64) NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())''')
        for path in sorted(root.glob('*.sql')):
            source=path.read_text(encoding='utf-8').replace('\r\n','\n')
            digest=hashlib.sha256(source.encode()).hexdigest()
            previous=conn.execute('SELECT sha256 FROM schema_migrations WHERE name=%s',(path.name,)).fetchone()
            if previous:
                if previous['sha256']!=digest:
                    raise RuntimeError(f'Migration changed after application: {path.name}')
                continue
            conn.execute(source)
            conn.execute('INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)',(path.name,digest))
            print('APPLIED '+path.name)
    print('MIGRATIONS_OK')


if __name__=='__main__':
    main()
