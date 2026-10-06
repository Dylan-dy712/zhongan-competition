"""Run account integration in a temporary PostgreSQL schema without updating services."""
import argparse
import io
from pathlib import Path, PurePosixPath
import shlex
import sys
import tarfile
import threading

import paramiko


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--key',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    files=sorted((root/'services').rglob('*.py'))+sorted((root/'services/api/sql').glob('*.sql'))+[root/'tests/test_accounts.py']
    files=[path for path in files if '__pycache__' not in path.parts]
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as package:
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise RuntimeError('Refusing linked source')
            data=path.read_bytes().replace(b'\r\n',b'\n')
            info=tarfile.TarInfo(path.relative_to(root).as_posix());info.mode=0o600;info.size=len(data)
            package.addfile(info,io.BytesIO(data))
    archive.seek(0)
    client=paramiko.SSHClient();client.load_system_host_keys();client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host,username='ubuntu',key_filename=args.key,timeout=15,allow_agent=False,look_for_keys=False)
    remote=None
    try:
        _,out,err=client.exec_command('umask 077; install -d -m 700 /home/ubuntu/zhongan-tests; mktemp -d /home/ubuntu/zhongan-tests/accounts-XXXXXXXX')
        remote=out.read().decode().strip()
        if out.channel.recv_exit_status() or PurePosixPath(remote).parent!=PurePosixPath('/home/ubuntu/zhongan-tests') or not PurePosixPath(remote).name.startswith('accounts-'):
            raise RuntimeError('Invalid isolated test directory')
        with client.open_sftp() as sftp:sftp.putfo(archive,remote+'/source.tar.gz')
        # Credentials stay on the host and never appear in output or uploaded source.
        command=('set -eu; cd '+shlex.quote(remote)+'; tar -xzf source.tar.gz; set -a; '
                 '. /home/ubuntu/.config/zhongan/database.env; set +a; '
                 'export ZHONGAN_AUTH_TEST_DATABASE_URL="$ZHONGAN_DATABASE_URL"; '
                 '/home/ubuntu/zhongan-app/.venv/bin/python -m pip install --quiet --disable-pip-version-check '
                 '--index-url https://pypi.org/simple --target test-dependencies httpx2==2.13.1; '
                 'export PYTHONPATH="$PWD/test-dependencies"; '
                 '/home/ubuntu/zhongan-app/.venv/bin/python -m unittest discover -s tests -p test_accounts.py -v')
        _,out,err=client.exec_command('bash -c '+shlex.quote(command),timeout=180)
        def drain(stream,target):
            for line in iter(stream.readline,''):target.write(line);target.flush()
        threads=[threading.Thread(target=drain,args=(out,sys.stdout)),threading.Thread(target=drain,args=(err,sys.stderr))]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        result=out.channel.recv_exit_status()
        print('ISOLATED_ACCOUNT_TEST_EXIT='+str(result))
        return result
    finally:
        if remote:
            # Delete only the exact allocated directory via SFTP; no shell-built rm.
            with client.open_sftp() as sftp:
                def remove_tree(directory):
                    import stat
                    for item in sftp.listdir_attr(directory):
                        path=directory+'/'+item.filename
                        if stat.S_ISDIR(item.st_mode):remove_tree(path)
                        else:sftp.remove(path)
                    sftp.rmdir(directory)
                if PurePosixPath(remote).parent==PurePosixPath('/home/ubuntu/zhongan-tests') and PurePosixPath(remote).name.startswith('accounts-'):
                    remove_tree(remote)
        client.close()


if __name__=='__main__':raise SystemExit(main())
