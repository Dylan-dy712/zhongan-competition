"""Verify vendored Semantix source and build the offline ranker for this host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'services/memory-ranker'
    for path, digest in json.loads((source / 'upstream-sha256.json').read_text(encoding='utf-8')).items():
        content = (source / 'third_party/semantix' / path).read_text(encoding='utf-8').replace('\r\n', '\n')
        if hashlib.sha256(content.encode()).hexdigest() != digest:
            raise RuntimeError('Vendored source checksum mismatch: ' + path)
    output = root / 'output_dir/memory-ranker'
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'GOPROXY': 'off', 'GOSUMDB': 'off', 'GOTOOLCHAIN': 'local',
           'GOCACHE': str(output / 'go-cache')}
    executable = output / ('semantix-ranker.exe' if os.name == 'nt' else 'semantix-ranker')
    subprocess.run(['go', 'build', '-trimpath', '-o', str(executable), '.'], cwd=source, env=env, check=True)
    print(str(executable))


if __name__ == '__main__':
    main()
