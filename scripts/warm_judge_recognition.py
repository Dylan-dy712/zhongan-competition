"""Prepare OCR artifacts for the fixed reviewed sample; no account, case or report is created."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from services.judge_demo.app import sample_manifest
from services.api.app.worker import route_document,recognition_profile
from services.api.app.judge_sample_cache import read_sample_pages,write_sample_pages


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--from-worker-environment',action='store_true',help='Use the running local Worker OCR configuration without printing credentials')
    args=parser.parse_args()
    if args.from_worker_environment:
        pid=subprocess.check_output(['systemctl','show','zhongan-worker','-p','MainPID','--value'],text=True).strip()
        if not pid.isdigit() or pid=='0':raise RuntimeError('WORKER_NOT_RUNNING')
        values=dict(item.split('=',1) for item in Path('/proc',pid,'environ').read_bytes().decode().split('\0') if '=' in item)
        os.environ.update({key:value for key,value in values.items() if key.startswith(('ZHONGAN_OCR_','VOLCENGINE_','TENCENTCLOUD_'))
            or key in {'ZHONGAN_JUDGE_SAMPLE_ROOT','ZHONGAN_JUDGE_RECOGNITION_ROOT'}})
    started=time.monotonic()
    directory,manifest=sample_manifest()
    fingerprint,versions=recognition_profile('document-parser-v1')
    count=reused=0
    for item in manifest['documents']:
        source=directory/item['file']
        if hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('SAMPLE_HASH_MISMATCH')
        existing=read_sample_pages(manifest,item,fingerprint,versions)
        pages=route_document({'media_type':item['media_type'],'source_hash':item['sha256']},source,
                             'document-parser-v1',cached=existing)
        if len(pages)!=item['page_count']:raise RuntimeError('SAMPLE_PAGE_COUNT_MISMATCH')
        count+=write_sample_pages(manifest,item,fingerprint,pages,versions)
        reused+=len(existing)
    print(json.dumps({'sample_id':manifest['sample_id'],'version':manifest['version'],
        'prepared_pages':count,'total_pages':manifest['page_count'],'previously_prepared_pages':reused,
        'seconds':round(time.monotonic()-started,3),'created_cases':0,'generated_reports':0}))


if __name__=='__main__':main()
