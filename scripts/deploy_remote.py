"""Upload an allowlisted committed release plus the production web build, then update."""
import argparse
import io
import shlex
import subprocess
import tarfile
import threading
import sys
from pathlib import Path

import paramiko


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    args = parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain']).strip():
        raise SystemExit('Commit all intended changes before deploying')
    revision = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    roots = ('services/', 'scripts/', 'deploy/', 'contracts/knowledge/', 'docs/medical/knowledge/')
    committed = subprocess.check_output(['git','archive','--format=tar','HEAD',*roots])
    artifact = io.BytesIO()
    with tarfile.open(fileobj=artifact, mode='w:gz') as archive:
        # Read committed blobs, not CRLF-converted Windows working-tree files.
        with tarfile.open(fileobj=io.BytesIO(committed),mode='r:') as source:
            for member in source:
                archive.addfile(member, source.extractfile(member) if member.isfile() else None)
        for path in Path('apps/web/dist').rglob('*'):
            if path.is_file():
                archive.add(path, arcname=path.as_posix())
        info = tarfile.TarInfo('REVISION')
        content = (revision+'\n').encode()
        info.size = len(content)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(content))
    artifact.seek(0)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username='ubuntu',key_filename=args.key,
        timeout=15,allow_agent=False,look_for_keys=False)
    try:
        _,out,err = client.exec_command('install -d -m 700 /home/ubuntu/zhongan-releases && mktemp -d /home/ubuntu/zhongan-releases/release-XXXXXXXX')
        remote = out.read().decode().strip()
        if out.channel.recv_exit_status() or not remote.startswith('/home/ubuntu/zhongan-releases/release-'):
            raise RuntimeError('Could not create release directory')
        with client.open_sftp() as sftp:
            sftp.putfo(artifact,remote+'/release.tar.gz')
        command = f'cd {shlex.quote(remote)} && tar -xzf release.tar.gz && bash scripts/deploy_update_ubuntu.sh'
        _,out,err = client.exec_command(command,timeout=600)
        def drain(stream,target):
            for line in iter(stream.readline,''):
                target.write(line)
                target.flush()
        threads=[threading.Thread(target=drain,args=(out,sys.stdout)),threading.Thread(target=drain,args=(err,sys.stderr))]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        raise SystemExit(out.channel.recv_exit_status())
    finally:
        client.close()


if __name__ == '__main__':
    main()
