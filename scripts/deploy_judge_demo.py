"""Ship and natively test the independent judge entry before optional installation."""
import argparse
import hashlib
import json
import shlex
import sys
import threading
from pathlib import Path, PurePosixPath

import paramiko

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'services/judge_demo/app.py', 'services/judge_demo/index.html',
    'services/judge_demo/entry.js', 'services/judge_demo/prepare.py',
    'tests/test_judge_demo.py', 'deploy/zhongan-judge-demo.service',
    'deploy/nginx-zhongan-judge-entry.conf', 'deploy/install_judge_demo_ubuntu.sh',
]
# Native verification imports the candidate API as well as the standalone entry.
FILES += ['services/__init__.py','services/api/__init__.py']
FILES += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT/'services/api/app').rglob('*.py')) if '__pycache__' not in path.parts]


def run(client, command):
    _, out, err = client.exec_command(command, timeout=360)
    def drain(stream, target):
        for line in iter(stream.readline, ''):
            target.write(line)
            target.flush()
    threads = [threading.Thread(target=drain, args=(out,sys.stdout)), threading.Thread(target=drain, args=(err,sys.stderr))]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    if out.channel.recv_exit_status():
        raise RuntimeError('Judge entry verification or installation failed; see diagnostics above')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in FILES}
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username='ubuntu', key_filename=args.key, timeout=15, allow_agent=False, look_for_keys=False)
    try:
        _, out, err = client.exec_command('umask 077; install -d -m 700 /home/ubuntu/zhongan-judge-releases; mktemp -d /home/ubuntu/zhongan-judge-releases/release-XXXXXXXX')
        release = out.read().decode().strip()
        if out.channel.recv_exit_status() or PurePosixPath(release).parent != PurePosixPath('/home/ubuntu/zhongan-judge-releases') or not PurePosixPath(release).name.startswith('release-'):
            raise RuntimeError('Invalid judge release path')
        with client.open_sftp() as sftp:
            directories = set()
            for name in FILES:
                path = ROOT/name
                if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                    raise RuntimeError('Refusing linked or escaped source')
                remote = PurePosixPath(release)/name
                for directory in reversed(remote.parents):
                    if str(directory).startswith(release + '/') and str(directory) not in directories:
                        sftp.mkdir(str(directory), mode=0o700)
                        directories.add(str(directory))
                with sftp.open(str(remote),'wb') as handle:
                    handle.write(path.read_bytes().replace(b'\r\n',b'\n'))
                sftp.chmod(str(remote),0o600)
            with sftp.open(release+'/source-manifest.json','w') as handle:
                handle.write(json.dumps(hashes,indent=2))
        # Native tests create/drop only their randomized temporary schema.
        command = ('set -eu; set -a; . /home/ubuntu/.config/zhongan/database.env; set +a; '
                   'export ZHONGAN_AUTH_TEST_DATABASE_URL="$ZHONGAN_DATABASE_URL"; '
                   'export ZHONGAN_TEST_MIGRATIONS_DIR=/home/ubuntu/zhongan-app/services/api/sql; '
                   'export PYTHONPATH='+shlex.quote(release+':/home/ubuntu/zhongan-app')+'; cd '+shlex.quote(release)+'; '
                   '/home/ubuntu/zhongan-app/.venv/bin/python -m unittest discover -s '+shlex.quote(release+'/tests')+' -p test_judge_demo.py -v; '
                   'bash -n '+shlex.quote(release+'/deploy/install_judge_demo_ubuntu.sh'))
        run(client, 'bash -c '+shlex.quote(command))
        if args.install:
            run(client, 'bash '+shlex.quote(release+'/deploy/install_judge_demo_ubuntu.sh')+' '+shlex.quote(release))
        receipt = {'release': release, 'source_sha256': hashes, 'native_tests': 'passed', 'installed': args.install}
        output = ROOT/'output_dir/judge-demo'
        output.mkdir(parents=True,exist_ok=True)
        (output/'deployment.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps({'native_tests':'passed', 'installed':args.install, 'release':release}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
