"""Package the standalone prototype; no medical documents or local uploads."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


def build_preview(source, output, revision, base='/mobile-demo/'):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Expected a full Git revision')
    if not re.fullmatch(r'/(?:[\w.-]+/)+', base) or '..' in base.split('/'):
        raise ValueError('Expected a local absolute directory base')
    entry = source/'home-proposal.html'
    if entry.is_symlink() or not entry.resolve().is_relative_to(source.resolve()):
        raise ValueError('Linked or escaped entry')
    html = entry.read_text(encoding='utf-8')
    # Resource URLs are immutable; a <base> would also redirect hash-only history URLs.
    html = html.replace('<head>', '<head>\n<meta name="artifact-base" content="'+base+'">\n'
                        '<script>if(!location.hash)location.hash="/home";</script>', 1)
    html = re.sub(r'(?<=\?v=)[\w-]+', revision, html)
    files = set(re.findall(r'(?:src|href)="([\w-]+\.(?:js|css))\?', html))
    assets = set()
    for name in sorted(files):
        path = source/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('Missing or linked source: '+name)
        content = path.read_text(encoding='utf-8')
        assets.update(re.findall(r'assets/([\w-]+\.webp)', content))
        if name == 'proposal-flow.js':
            assets.update({'onboard-document.webp', 'onboard-heart.webp', 'onboard-chat.webp'})
    for name in assets:
        path = source/'assets'/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('Missing or linked asset: '+name)
    for name in files:
        html = html.replace('"'+name+'?', '"'+base+name+'?')
    html = html.replace('assets/', base+'assets/')
    output.mkdir(parents=True, exist_ok=False)
    (output/'index.html').write_text(html, encoding='utf-8')
    (output/'CI_REVISION').write_text(revision+'\n', encoding='utf-8')
    for name in files:
        content = (source/name).read_text(encoding='utf-8')
        (output/name).write_text(content.replace('assets/', base+'assets/'), encoding='utf-8')
    (output/'assets').mkdir()
    for name in assets:
        shutil.copyfile(source/'assets'/name, output/'assets'/name)
    manifest = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n', encoding='utf-8')
    return {'revision': revision, 'build': str(output), 'file_count': len(manifest)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='output_dir/mobile-demo/dist')
    parser.add_argument('--revision', default=None)
    parser.add_argument('--base', default='/mobile-demo/')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = args.revision or subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    print(json.dumps(build_preview(root/'output_dir/product-design', Path(args.output), revision, args.base)))


if __name__ == '__main__':
    main()
