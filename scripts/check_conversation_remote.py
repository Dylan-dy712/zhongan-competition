"""Upload current source to an isolated remote temp directory and run integration checks.

Uses Paramiko with known-host verification. Does not deploy or restart services.
The integration runner creates and removes only a random test schema.
"""
import argparse
import io
import shlex
import tarfile
from pathlib import Path

import paramiko


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--key',required=True)
    parser.add_argument('--test-deps',default='')
    parser.add_argument('--live-model',action='store_true')
    parser.add_argument('--trace-synthetic',action='store_true')
    parser.add_argument('--suite',choices=('conversation','review','release','all'),default='conversation')
    parser.add_argument('--skip-units',action='store_true',
                        help='skip unittest discover; use when unit tests need build artifacts '
                             'the source-only tarball does not ship (they run locally and in CI)')
    args=parser.parse_args()
    client=paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host,username='ubuntu',key_filename=args.key,timeout=15,allow_agent=False,look_for_keys=False)
    try:
        _,out,err=client.exec_command('mktemp -d /tmp/zhongan-chat-test.XXXXXXXX')
        remote=out.read().decode().strip()
        if out.channel.recv_exit_status()!=0 or not remote.startswith('/tmp/zhongan-chat-test.'):
            raise RuntimeError('Could not create isolated remote test directory')
        artifact=io.BytesIO()
        with tarfile.open(fileobj=artifact,mode='w:gz') as archive:
            for root in ('services','contracts/knowledge','docs/medical/knowledge','tests'):
                for path in Path(root).rglob('*'):
                    if path.is_file() and '__pycache__' not in path.parts:
                        archive.add(path,arcname=path.as_posix())
            for path in Path('scripts').glob('*.py'):
                archive.add(path,arcname=path.as_posix())
        artifact.seek(0)
        with client.open_sftp() as sftp:
            sftp.putfo(artifact,remote+'/source.tar.gz')
        suites=('review','conversation','release') if args.suite=='all' else (args.suite,)
        commands={'conversation':'check_conversation_integration','review':'check_review_integration','release':'check_release_integration'}
        python='/home/ubuntu/zhongan-app/.venv/bin/python'
        command=(f'cd {shlex.quote(remote)} && tar -xzf source.tar.gz && '
            'set -a && . /home/ubuntu/.config/zhongan/database.env && set +a && '
            + (f'export PYTHONPATH={shlex.quote(args.test_deps)} && ' if args.test_deps else '')
            + ('set -a && . /home/ubuntu/.config/zhongan/llm.env && set +a && export CHAT_LIVE_SMOKE=1 && ' if args.live_model else '')
            + ('export CHAT_TRACE_SYNTHETIC=1 && ' if args.trace_synthetic else '')
            + ('' if args.skip_units else f'{python} -m unittest discover -s tests -q && ')
            + ' && '.join(f'{python} -m scripts.{commands[suite]}' for suite in suites))
        _,out,err=client.exec_command('bash -lc '+shlex.quote(command),timeout=240)
        stdout,stderr=out.read().decode(),err.read().decode()
        print(stdout)
        print(stderr)
        code=out.channel.recv_exit_status()
        print('ISOLATED_TEST_DIRECTORY='+remote)
        if code:
            raise SystemExit(code)
    finally:
        client.close()


if __name__=='__main__':
    main()
