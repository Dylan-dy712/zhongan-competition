"""Compare the public preview with its exact successful CI artifact."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from scripts.deploy_remote import validated_build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--artifact', required=True, type=Path)
    args = parser.parse_args()
    files = validated_build(args.artifact, args.revision, mobile=True)
    base = 'http://'+args.host
    for path in files:
        name = path.relative_to(args.artifact).as_posix()
        with urlopen(base+'/mobile-demo/'+name, timeout=20) as response:
            if response.status!=200 or hashlib.sha256(response.read()).digest()!=hashlib.sha256(path.read_bytes()).digest():
                raise RuntimeError('Public file mismatch: '+name)
        # The document's immutable base must resolve to the same artifact.
        with urlopen(base+'/.mobile-demo-releases/'+args.revision+'/'+name, timeout=20) as response:
            if response.status!=200 or response.read()!=path.read_bytes():
                raise RuntimeError('Immutable release mismatch: '+name)
    with urlopen(base+'/health', timeout=20) as response:
        if response.status!=200 or json.loads(response.read())['status']!='ok':
            raise RuntimeError('API health failed')
    with urlopen(base+'/', timeout=20) as response:
        if response.status!=200:
            raise RuntimeError('Primary web failed')
    print(json.dumps({'revision':args.revision, 'url':base+'/mobile-demo/', 'files_verified':len(files),
                      'immutable_files_verified':len(files), 'root_status':200, 'health_status':200}))


if __name__ == '__main__':
    main()
