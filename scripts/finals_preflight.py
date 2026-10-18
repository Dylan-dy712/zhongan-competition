"""Check frozen inputs and runtime configuration without exposing credentials."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import os
import re
import io
import json
import time
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
                'tencent_table': ('TENCENTCLOUD_SECRET_ID', 'TENCENTCLOUD_SECRET_KEY'),
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
        'duplicate_ids', 'invalid_ids', 'missing_images', 'missing_ocr', 'changed_ocr', 'empty_ocr', 'changed_references'))
    result['image_hash_validated'] = False
    return result


def live_probes(config, include_table):
    from PIL import Image, ImageDraw, ImageFont
    from services.api.app.ocr import create_ocr
    from services.api.app.llm_extractor import OpenAiCompatibleExtractor
    image = Image.new('RGB', (1100,300), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    draw.text((20,15), 'OCR READINESS 2026', fill='black', font=font)
    for x in (20,520,1050):
        draw.line((x,80,x,260), fill='black', width=2)
    for y in (80,140,200,260):
        draw.line((20,y,1050,y), fill='black', width=2)
    for x,y,text in ((35,95,'Item'),(540,95,'Total'),(35,155,'Example A'),
                     (540,155,'12.34'),(35,215,'Example B'),(540,215,'56.78')):
        draw.text((x,y),text,fill='black',font=font)
    stream=io.BytesIO()
    image.save(stream,format='PNG')
    def probe(fn):
        start=time.monotonic()
        try:
            result=fn()
            return {**result,'seconds':round(time.monotonic()-start,3)}
        except Exception as exc:
            result={'status':'failed','error_code':type(exc).__name__}
            response=getattr(exc,'response',None)
            if response is not None:
                result['http_status']=response.status_code
            safe=re.fullmatch(r'OCR_PROVIDER_ERROR:([A-Za-z0-9_.-]{1,120})',str(exc))
            if safe:
                result['provider_code']=safe.group(1)
            return {**result,'seconds':round(time.monotonic()-start,3)}
    def ocr():
        result=create_ocr().recognize(stream.getvalue(),1100,300)
        return {'status':'ok' if result.get('text','').strip() else 'empty'}
    def table():
        client=create_ocr()
        if not callable(getattr(client,'recognize_table',None)):
            return {'status':'unsupported'}
        result=client.recognize_table(stream.getvalue(),1100,300)
        return {'status':'ok' if result.get('tables') else 'empty'}
    def model():
        payload,content=OpenAiCompatibleExtractor()._call([
            {'role':'system','content':'Return only the JSON object {"ok":true}.'},
            {'role':'user','content':'Runtime readiness probe; no medical data.'}],
            timeout=(10,45),workload='title')
        value=json.loads(content)
        return {'status':'ok' if isinstance(value,dict) and value.get('ok') is True else 'invalid_output',
                'total_tokens':payload.get('usage',{}).get('total_tokens')}
    result={}
    result['ocr']=probe(ocr) if config['ocr_configured'] else {'status':'not_configured'}
    if include_table:
        result['table_ocr']=probe(table) if config['ocr_configured'] else {'status':'not_configured'}
    result['model']=probe(model) if config['model_configured'] else {'status':'not_configured'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', action='append', default=[], help='private JSON; later files override earlier ones')
    parser.add_argument('--manifest', help='optional prepared OCR input manifest')
    parser.add_argument('--output', required=True)
    parser.add_argument('--ocr-provider', choices=['tencent','tencent_table','volcengine'])
    parser.add_argument('--live', action='store_true', help='make one synthetic OCR and model probe; may consume quota')
    parser.add_argument('--table', action='store_true', help='also probe table OCR; requires --live')
    args = parser.parse_args()
    if args.table and not args.live:
        parser.error('--table requires --live')
    repo = Path(__file__).resolve().parents[1]
    if Path(args.output).resolve().is_relative_to(repo):
        parser.error('readiness output must remain outside the repository')
    for path in args.config:
        os.environ.update({k: str(v) for k,v in load(path).items()
                           if k.startswith(('LLM_', 'TENCENTCLOUD_', 'VOLCENGINE_', 'ZHONGAN_'))})
    if args.ocr_provider:
        os.environ['ZHONGAN_OCR_PROVIDER']=args.ocr_provider
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
    if args.live:
        report['services']=live_probes(config,args.table)
        report['live_services_verified']=all(value['status']=='ok' for value in report['services'].values())
        passed = passed and report['live_services_verified']
        report['checks_passed']=bool(passed)
        report['status']='ready_for_rehearsal' if passed else 'blocked'
    write(args.output, report)
    print(__import__('json').dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
