"""Download pinned public model files with integrity checks; run before deployment."""
import argparse
import hashlib
import json
from pathlib import Path

import requests

from services.api.app.knowledge_vectors import MANIFEST, MODEL_REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-dir', required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['revision'] == MODEL_REVISION
    destination = Path(args.cache_dir) / MODEL_REVISION
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('INVALID_MODEL_PATH')
        path = destination / name
        if path.exists():
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == expected:
                    continue
        temporary = destination / (name + '.part')
        url = f"https://huggingface.co/{manifest['repository']}/resolve/{MODEL_REVISION}/{name}"
        with requests.get(url, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            with temporary.open('wb') as stream:
                for block in response.iter_content(1024 * 1024):
                    digest.update(block)
                    stream.write(block)
        if digest.hexdigest() != expected:
            raise ValueError('MODEL_DOWNLOAD_INTEGRITY_FAILED')
        temporary.replace(path)
    print('EMBEDDING_FILES_VERIFIED revision=' + MODEL_REVISION)


if __name__ == '__main__': main()
