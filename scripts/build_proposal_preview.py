"""Package only the current standalone prototype and its referenced assets."""
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

root=Path(__file__).resolve().parents[1]
source=root/'output_dir/product-design'
name='proposal-release-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
build=root/'output_dir/mobile-demo'/name
build.mkdir(parents=True,exist_ok=False)
html=(source/'home-proposal.html').read_text(encoding='utf-8')
html=html.replace('<head>','<head>\n<base href="/mobile-demo/">',1)
html=re.sub(r'(?<=\?v=)[\w-]+',name,html)
(build/'index.html').write_text(html,encoding='utf-8')
files=set(re.findall(r'(?:src|href)="([\w-]+\.(?:js|css))\?',html))
assets=set()
for name in sorted(files):
    path=source/name
    if not path.is_file():raise RuntimeError('Missing referenced file: '+name)
    content=path.read_text(encoding='utf-8')
    assets.update(re.findall(r'assets/([\w-]+\.webp)',content))
    # Template interpolation builds these first-visit illustration names.
    if name=='proposal-flow.js':assets.update({'onboard-document.webp','onboard-heart.webp','onboard-chat.webp'})
    shutil.copy2(path,build/name)
(build/'assets').mkdir()
for name in sorted(assets):
    path=source/'assets'/name
    if not path.is_file():raise RuntimeError('Missing referenced asset: '+name)
    shutil.copy2(path,build/'assets'/name)
manifest={p.relative_to(build).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(build.rglob('*')) if p.is_file()}
(root/'output_dir/mobile-demo/latest-build.json').write_text(json.dumps({'build':str(build),'files':manifest},indent=2),encoding='utf-8')
print(json.dumps({'build':str(build),'file_count':len(manifest),'assets':len(assets)}))
