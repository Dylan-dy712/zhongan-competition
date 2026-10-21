"""Publish an exact fixed sample from existing OCR; prepare fields once, never a report."""
import argparse,copy,hashlib,io,json,os,subprocess,time
from pathlib import Path
import pypdfium2 as pdfium
from services.judge_demo.app import sample_manifest
from services.api.app import product_extraction as product
from services.api.app.parse_cache import payload_digest
from services.api.app.judge_sample_cache import (cache_path,read_sample_pages,write_sample_pages,
    extraction_identity,prepared_page_compatible,publish_prepared_library)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-profile',required=True)
    args=parser.parse_args()
    pid=subprocess.check_output(['systemctl','show','zhongan-worker','-p','MainPID','--value'],text=True).strip()
    if not pid.isdigit() or pid=='0':raise RuntimeError('WORKER_NOT_RUNNING')
    values=dict(x.split('=',1) for x in Path('/proc',pid,'environ').read_bytes().decode().split('\0') if '=' in x)
    os.environ.update({k:v for k,v in values.items() if k.startswith(('ZHONGAN_','LLM_'))})
    directory,manifest=sample_manifest()
    target_profile=payload_digest({'preparation':'reviewed-library-v1','source_profile':args.source_profile,
        'extraction':extraction_identity()})
    total=0;started=time.monotonic()
    for item in manifest['documents']:
        path=directory/item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('SAMPLE_HASH_MISMATCH')
        source=cache_path(manifest,item,args.source_profile)
        if source.is_symlink() or source.stat().st_size>8*1024*1024:raise RuntimeError('INVALID_SOURCE_ARTIFACT')
        payload=json.loads(source.read_text(encoding='utf-8'))
        versions={p['parser_version'] for p in payload['pages']}
        pages=read_sample_pages(manifest,item,args.source_profile,versions)
        if set(pages)!=set(range(item['page_count'])):raise RuntimeError('SOURCE_RECOGNITION_INCOMPLETE')
        ready=read_sample_pages(manifest,item,target_profile,versions)
        pdf=pdfium.PdfDocument(str(path))
        try:
            for index,page in pages.items():
                if index in ready and prepared_page_compatible(ready[index]):continue
                page=copy.deepcopy(page)
                if product.enabled():
                    pdf_page=pdf[index];bitmap=pdf_page.render(scale=2.0)
                    try:
                        image=bitmap.to_pil().convert('RGB');buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=92)
                        image_bytes=buffer.getvalue();image.close()
                    finally:bitmap.close();pdf_page.close()
                    plan=product.layout(image_bytes)
                    page['metadata']['material_layout']=plan
                    # Keep original OCR text, version and boxes; visual field sources remain marked.
                    page=product.extract_page(page,image_bytes,plan)
                if not prepared_page_compatible(page):raise RuntimeError('PAGE_PREPARATION_INCOMPLETE')
                ready[index]=page
                write_sample_pages(manifest,item,target_profile,list(ready.values()),versions)
                print(json.dumps({'document':item['id'],'prepared_page':index+1,'pages':item['page_count'],
                    'extraction_status':page['metadata'].get('document_extraction',{}).get('status'),
                    'ocr_requests':0,'generated_reports':0}),flush=True)
        finally:pdf.close()
        total+=len(ready)
    all_versions=set()
    for item in manifest['documents']:
        payload=json.loads(cache_path(manifest,item,target_profile).read_text(encoding='utf-8'))
        all_versions.update(p['parser_version'] for p in payload['pages'])
    publish_prepared_library(manifest,target_profile,all_versions)
    print(json.dumps({'published':True,'sample_id':manifest['sample_id'],'version':manifest['version'],
        'prepared_pages':total,'seconds':round(time.monotonic()-started,2),'ocr_requests':0,'generated_reports':0}),flush=True)


if __name__=='__main__':main()
