"""Deploy only the mobile preview's static files to an isolated server subpath."""
import argparse
import hashlib
import json
import shlex
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paramiko


REMOTE_INSTALL = r'''
import json, os, shutil, sys
from pathlib import Path
stage, release = Path(sys.argv[1]), sys.argv[2]
root = Path('/var/www/zhongan-web')
assert stage.parent == Path('/home/ubuntu/zhongan-releases')
assert stage.name == release and release.startswith('mobile-preview-')
target = root / 'mobile-demo'
if target.exists() and not target.is_symlink():
    raise RuntimeError('Existing mobile-demo directory requires separate review')
previous = os.readlink(target) if target.is_symlink() else None
build = root / '.mobile-demo-releases' / release
assert not build.exists()
shutil.copytree(stage / 'dist', build)
for directory, _, files in os.walk(build):
    os.chmod(directory, 0o755)
    for name in files:
        os.chmod(Path(directory) / name, 0o644)
os.chmod(build.parent, 0o755)
link = root / ('.mobile-demo-next-' + release)
os.symlink('.mobile-demo-releases/' + release, link)
os.replace(link, target)
print(json.dumps({'release': release, 'previous': previous, 'preview_path': '/mobile-demo/'}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--build', default=None, help='Defaults to the current standalone build receipt')
    parser.add_argument('--entry-route', choices=['/demo/today', '/welcome', '/claim'], default='/claim')
    args = parser.parse_args()
    selected_build = args.build or json.loads(Path('output_dir/mobile-demo/latest-build.json').read_text(encoding='utf-8'))['build']
    build = Path(selected_build).resolve()
    index = build / 'index.html'
    content = index.read_text(encoding='utf-8')
    if '/mobile-demo/assets/' not in content and '<base href="/mobile-demo/">' not in content:
        raise SystemExit('Build using --base=/mobile-demo/ before deployment')
    # The direct phone URL opens the Demo without requiring a hash to be typed.
    entry = '<script>if(!location.hash)location.hash=' + json.dumps(args.entry_route) + ';</script>'
    if entry not in content:
        content = content.replace('<head>', '<head>\n    ' + entry, 1)
        index.write_text(content, encoding='utf-8')
    files = sorted(p for p in build.rglob('*') if p.is_file())
    if any(p.is_symlink() or not p.resolve().is_relative_to(build) for p in files):
        raise SystemExit('Unexpected build path')
    manifest = {p.relative_to(build).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    release = 'mobile-preview-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    stage = '/home/ubuntu/zhongan-releases/' + release
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username='ubuntu', key_filename=args.key, timeout=15, allow_agent=False, look_for_keys=False)
    try:
        with client.open_sftp() as sftp:
            sftp.mkdir(stage, mode=0o755)
            sftp.mkdir(stage + '/dist', mode=0o755)
            created = {'.'}
            for file in files:
                relative = file.relative_to(build)
                for parent in reversed(relative.parents):
                    if parent.as_posix() not in created:
                        sftp.mkdir(stage + '/dist/' + parent.as_posix(), mode=0o755)
                        created.add(parent.as_posix())
                sftp.put(str(file), stage + '/dist/' + relative.as_posix())
            # Verify uploaded bytes before publishing the symlink.
            for relative, digest in manifest.items():
                with sftp.open(stage + '/dist/' + relative, 'rb') as remote_file:
                    if hashlib.sha256(remote_file.read()).hexdigest() != digest:
                        raise RuntimeError('Uploaded artifact checksum mismatch')
        command = 'python3 -c ' + shlex.quote(REMOTE_INSTALL) + ' ' + shlex.quote(stage) + ' ' + shlex.quote(release)
        _, out, err = client.exec_command(command, timeout=60)
        output, error = out.read().decode(), err.read().decode()
        if out.channel.recv_exit_status():
            raise RuntimeError(error)
        receipt = json.loads(output)
        receipt.update({'url': f'http://{args.host}/mobile-demo/', 'files': manifest})
        receipt_path = Path('output_dir/mobile-demo/deployment.json')
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in receipt.items() if k != 'files'}, ensure_ascii=False))
    finally:
        client.close()


if __name__ == '__main__':
    main()
