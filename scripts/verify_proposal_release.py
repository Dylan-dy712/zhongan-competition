"""Verify public files against the deployment receipt, without business requests."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

receipt=json.loads(Path('output_dir/mobile-demo/deployment.json').read_text(encoding='utf-8'))
base=receipt['url']
for name,digest in receipt['files'].items():
    with urlopen(base+name,timeout=20) as response:
        actual=hashlib.sha256(response.read()).hexdigest()
        if response.status!=200 or actual!=digest:raise RuntimeError('Public file mismatch: '+name)
with urlopen(base+'index.html',timeout=20) as response:html=response.read().decode()
assert 'location.hash="/claim"' in html
assert 'claim-entry.js' in html and 'expense-reference.css' in html
with urlopen('http://49.235.108.92/health',timeout=20) as response:
    assert response.status==200
with urlopen('http://49.235.108.92/',timeout=20) as response:
    assert response.status==200
result={'release':receipt['release'],'verified_at':datetime.now(timezone.utc).isoformat(),'url':base,'files_verified':len(receipt['files']),'entry':'/claim','root_status':200,'health_status':200}
Path('output_dir/mobile-demo/public-release-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
