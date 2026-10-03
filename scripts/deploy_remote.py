"""Upload an allowlisted committed release plus the production web build, then update."""
import argparse
import hashlib
import io
import json
import shlex
import subprocess
import tarfile
import threading
import sys
import tempfile
from pathlib import Path


def validated_build(root, revision, *, mobile=False):
    if not (root/'index.html').is_file() or (root/'CI_REVISION').read_text().strip()!=revision:
        raise SystemExit('CI artifact does not match the deployed revision')
    paths = sorted(p for p in root.rglob('*') if p.is_file())
    if any(p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) for p in root.rglob('*')):
        raise SystemExit('Linked or escaped CI artifact path')
    if mobile:
        manifest = json.loads((root/'manifest.json').read_text())
        actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in paths if p!=root/'manifest.json'}
        if manifest!=actual:
            raise SystemExit('Mobile artifact manifest mismatch')
        if '<base href="/.mobile-demo-releases/'+revision+'/">' not in (root/'index.html').read_text(encoding='utf-8'):
            raise SystemExit('Mobile artifact must use its immutable release base')
    return paths

def verified_ci_run(revision):
    remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/main'],text=True).split()
    if not remote or remote[0]!=revision:
        raise SystemExit('Deploy only the current remote main revision')
    runs=json.loads(subprocess.check_output(['gh','run','list','--repo','Dylan-dy712/zhongan-competition',
        '--workflow','ci.yml','--commit',revision,'--branch','main','--event','push','--limit','1',
        '--json','databaseId,status,conclusion,headSha,headBranch,event'],text=True))
    if (not runs or runs[0]['headSha']!=revision or runs[0]['headBranch']!='main' or runs[0]['event']!='push'
        or runs[0]['status']!='completed' or runs[0]['conclusion']!='success'):
        raise SystemExit('The exact main revision must pass CI before deployment')
    return runs[0]['databaseId']


def main():
    import paramiko
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    args = parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain']).strip():
        raise SystemExit('Commit all intended changes before deploying')
    revision = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    ci_run=verified_ci_run(revision)
    roots = ('services/', 'scripts/', 'deploy/', 'contracts/knowledge/', 'docs/medical/knowledge/')
    committed = subprocess.check_output(['git','archive','--format=tar','HEAD',*roots])
    artifact = io.BytesIO()
    with tarfile.open(fileobj=artifact, mode='w:gz') as archive:
        # Read committed blobs, not CRLF-converted Windows working-tree files.
        with tarfile.open(fileobj=io.BytesIO(committed),mode='r:') as source:
            for member in source:
                data = source.extractfile(member).read() if member.isfile() else None
                if data is not None and member.name.endswith('.sh'):
                    data = data.replace(b'\r\n', b'\n')
                    member.size = len(data)
                archive.addfile(member, io.BytesIO(data) if data is not None else None)
        for name, destination in [('web-dist','apps/web/dist/'),('mobile-dist','output_dir/mobile-demo/dist/')]:
            with tempfile.TemporaryDirectory(prefix='zhongan-ci-'+name+'-') as build:
                subprocess.check_call(['gh','run','download',str(ci_run),'--repo','Dylan-dy712/zhongan-competition',
                                       '--name',name,'--dir',build])
                root=Path(build)
                for path in validated_build(root, revision, mobile=name=='mobile-dist'):
                    archive.add(path,arcname=destination+path.relative_to(root).as_posix())
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
