"""Check frozen inputs and runtime configuration without exposing credentials."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import platform
import subprocess
import sys
from urllib.parse import urlparse
from scripts.preliminary_kr1 import load, sha, write
from services.api.app.document_fields import PROMPT_VERSION, SCHEMA_VERSION


def configuration():
    provider = os.getenv('ZHONGAN_OCR_PROVIDER', 'tencent')
    required = {'tencent': ('TENCENTCLOUD_SECRET_ID', 'TENCENTCLOUD_SECRET_KEY'),
                'volcengine': ('VOLCENGINE_OCR_ACCESS_KEY_ID', 'VOLCENGINE_OCR_SECRET_ACCESS_KEY')}
    host = urlparse(os.getenv('LLM_BASE_URL', '')).hostname
    return {'ocr_provider': provider,
        'ocr_configured': provider in required and all(os.getenv(k) for k in required[provider]),
        'model_id': os.getenv('LLM_MODEL_ID', '')[:100], 'model_host': host,
        'model_configured': bool(host and os.getenv('LLM_API_KEY') and os.getenv('LLM_MODEL_ID')
                                 and os.getenv('LLM_PROVIDER') != 'mock'),
        'notice': 'credential presence is not proof of quota or service availability'}


def inputs(path):
    manifest = load(path)
    ids = [row.get('document_id') for row in manifest['documents']]
    result = {'documents': len(ids), 'duplicate_ids': sum(n-1 for n in Counter(ids).values()),
              'invalid_ids': sum(not isinstance(x, str) or not x.strip() for x in ids),
              'missing_images': 0, 'missing_ocr': 0, 'changed_ocr': 0, 'empty_ocr': 0,
              'changed_references': 0, 'references_not_supplied': 0}
    for row in manifest['documents']:
        if not row.get('image') or not Path(row['image']).is_file():
            result['missing_images'] += 1
        if not row.get('ocr') or not Path(row['ocr']).is_file():
            result['missing_ocr'] += 1
        elif sha(row['ocr']) != row.get('ocr_sha256'):
            result['changed_ocr'] += 1
        elif not load(row['ocr']).get('text', '').strip():
            result['empty_ocr'] += 1
        if row.get('reference'):
            if not Path(row['reference']).is_file() or sha(row['reference']) != row.get('reference_sha256'):
                result['changed_references'] += 1
        else:
            result['references_not_supplied'] += 1
    result['passed'] = bool(ids) and not any(result[k] for k in (
        'duplicate_ids', 'invalid_ids', 'missing_images', 'missing_ocr', 'changed_ocr', 'changed_references'))
    result['image_hash_validated'] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', action='append', default=[], help='private JSON; later files override earlier ones')
    parser.add_argument('--manifest', help='optional prepared OCR input manifest')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if Path(args.output).resolve().is_relative_to(repo):
        parser.error('readiness output must remain outside the repository')
    for path in args.config:
        os.environ.update({k: str(v) for k,v in load(path).items()
                           if k.startswith(('LLM_', 'TENCENTCLOUD_', 'VOLCENGINE_', 'ZHONGAN_'))})
    config = configuration()
    dependencies = {name: importlib.util.find_spec(name) is not None
                    for name in ('PIL','pydantic','requests','psycopg','tencentcloud')}
    report = {'version': 'finals-runtime-preflight-v1',
        'checked_at': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
        'code_revision': subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'working_tree_dirty': bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo)),
        'prompt_version': PROMPT_VERSION, 'schema_version': SCHEMA_VERSION,
        'configuration': config, 'dependencies': dependencies,
        'live_services_verified': False, 'status': 'configuration_checked_not_live_verified'}
    if args.manifest:
        report['inputs'] = inputs(args.manifest)
    passed = (sys.version_info >= (3,11) and all(dependencies.values()) and config['ocr_configured']
              and config['model_configured'] and report.get('inputs',{}).get('passed',True))
    report['checks_passed'] = bool(passed)
    write(args.output, report)
    print(__import__('json').dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
