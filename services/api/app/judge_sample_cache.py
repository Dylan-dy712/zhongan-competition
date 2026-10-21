"""Private recognition artifacts for the reviewed demo library, never patient reports."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from .parse_cache import cacheable,payload_digest

FORMAT='reviewed-sample-recognition-v1'
PUBLISHED_FORMAT='reviewed-sample-preparation-v1'


def extraction_identity():
    """OCR provenance is stored per page; bind optional field extraction separately."""
    from . import product_extraction as product
    return payload_digest({'enabled':product.enabled(),
        'version':product.VERSION if product.enabled() else None,
        'prompt':product.PROMPT_VERSION if product.enabled() else None,
        'schema':product.SCHEMA_VERSION if product.enabled() else None,
        'provider':os.getenv('ZHONGAN_DOCUMENT_LLM_PROVIDER') if product.enabled() else None,
        'model':os.getenv('ZHONGAN_DOCUMENT_LLM_MODEL_ID') if product.enabled() else None,
        'base':os.getenv('ZHONGAN_DOCUMENT_LLM_BASE_URL') if product.enabled() else None})


def prepared_page_compatible(page):
    from . import product_extraction as product
    from .ocr import page_ocr_method
    from .worker import TEXT_PARSER_VERSION,PDF_PARSER_VERSION
    if not page_ocr_method(page) and page.get('parser_version') not in {TEXT_PARSER_VERSION,PDF_PARSER_VERSION}:
        return False
    if not product.enabled():return True
    record=page.get('metadata',{}).get('document_extraction',{})
    return (record.get('version')==product.VERSION and record.get('prompt_version')==product.PROMPT_VERSION
        and record.get('schema_version')==product.SCHEMA_VERSION
        and record.get('model_id')==os.getenv('ZHONGAN_DOCUMENT_LLM_MODEL_ID')
        and record.get('provider')==os.getenv('ZHONGAN_DOCUMENT_LLM_PROVIDER')
        and record.get('status') in {'completed','partial'})


def published_path():
    return Path(os.getenv('ZHONGAN_JUDGE_RECOGNITION_ROOT','/home/ubuntu/zhongan-data/judge-recognition'))/'prepared-library.json'


def publish_prepared_library(manifest,profile,versions):
    """Publish only a complete, verified fixed library; never copy account evidence IDs."""
    entries=[]
    for item in manifest['documents']:
        pages=read_sample_pages(manifest,item,profile,versions)
        if set(pages)!=set(range(item['page_count'])) or not all(prepared_page_compatible(p) for p in pages.values()):
            raise ValueError('SAMPLE_PREPARATION_INCOMPLETE')
        target=cache_path(manifest,item,profile)
        entries.append({'source_hash':item['sha256'],'page_count':item['page_count'],
            'artifact_profile':profile,'parser_versions':sorted({p['parser_version'] for p in pages.values()}),
            'artifact_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    data={'format':PUBLISHED_FORMAT,'sample_id':manifest['sample_id'],'version':manifest['version'],
        'extraction_identity':extraction_identity(),'documents':entries}
    path=published_path();temporary=path.with_suffix('.tmp-'+uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            os.chmod(temporary,0o600);json.dump(data,stream,separators=(',',':'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def published_sample_pages(manifest,item):
    """A reviewed library survives unrelated live OCR outages and provider switches."""
    try:
        path=published_path()
        if path.is_symlink() or path.stat().st_size>65536:return {}
        data=json.loads(path.read_text(encoding='utf-8'))
        expected={'format':PUBLISHED_FORMAT,'sample_id':manifest['sample_id'],'version':manifest['version'],
            'extraction_identity':extraction_identity()}
        if any(data.get(k)!=v for k,v in expected.items()):return {}
        matches=[d for d in data['documents'] if d['source_hash']==item['sha256']]
        if len(matches)!=1:return {}
        entry=matches[0]
        if entry['page_count']!=item['page_count']:return {}
        artifact=cache_path(manifest,item,entry['artifact_profile'])
        if artifact.is_symlink() or artifact.stat().st_size>8*1024*1024:return {}
        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=entry['artifact_sha256']:return {}
        pages=read_sample_pages(manifest,item,entry['artifact_profile'],set(entry['parser_versions']))
        if set(pages)!=set(range(item['page_count'])) or not all(prepared_page_compatible(p) for p in pages.values()):return {}
        return pages
    except (OSError,ValueError,KeyError,TypeError):return {}


def reusable_sample_page(page,accepted_versions):
    if not isinstance(page,dict) or set(page)-{'page_index','page_kind','text','content_hash','status',
            'requires_ocr','requires_vision','parser_version','blocks','metadata'}:
        return False
    if page.get('parser_version') not in accepted_versions or not isinstance(page.get('metadata'),dict):return False
    if type(page.get('page_index')) is not int:return False
    quality=page['metadata'].get('photo_quality') or {}
    if not isinstance(quality,dict):return False
    # The immutable library cannot become clearer by downloading identical bytes.
    # Keep every warning and excluded block; only already-readable text is reused.
    if quality.get('needs_reupload'):
        blocks=page.get('blocks') or []
        if not all(isinstance(block,dict) and isinstance(block.get('metadata'),dict) for block in blocks):return False
        readable='\n'.join(block['text'] for block in blocks
            if not block['metadata'].get('needs_clearer_photo') and isinstance(block.get('text'),str))
        if page.get('text')!=readable:return False
        checked=copy.deepcopy(page)
        checked['metadata']['photo_quality']['needs_reupload']=False
        return cacheable(checked)
    return cacheable(page)


def cache_path(manifest,item,fingerprint):
    for value in (item['sha256'],fingerprint):
        if not re.fullmatch(r'[0-9a-f]{64}',value):raise ValueError('INVALID_SAMPLE_CACHE_KEY')
    root=Path(os.getenv('ZHONGAN_JUDGE_RECOGNITION_ROOT','/home/ubuntu/zhongan-data/judge-recognition'))
    identity=payload_digest({'sample_id':manifest['sample_id'],'version':manifest['version'],
        'source_hash':item['sha256'],'parser_fingerprint':fingerprint})
    return root/(identity+'.json')


def write_sample_pages(manifest,item,fingerprint,pages,accepted_versions):
    kept=[page for page in pages if reusable_sample_page(page,accepted_versions)]
    if len({page['page_index'] for page in kept})!=len(kept):raise ValueError('DUPLICATE_SAMPLE_PAGE')
    if any(page['page_index']>=item['page_count'] for page in kept):raise ValueError('INVALID_SAMPLE_PAGE_INDEX')
    target=cache_path(manifest,item,fingerprint)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(target.parent,0o700)
    data={'format':FORMAT,'sample_id':manifest['sample_id'],'version':manifest['version'],
          'source_hash':item['sha256'],'parser_fingerprint':fingerprint,'pages':kept,'payload_sha256':payload_digest(kept)}
    temporary=target.with_suffix('.tmp-'+uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            os.chmod(temporary,0o600)
            json.dump(data,stream,ensure_ascii=False,separators=(',',':'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    return len(kept)


def read_sample_pages(manifest,item,fingerprint,accepted_versions):
    try:
        target=cache_path(manifest,item,fingerprint)
        if target.is_symlink() or target.stat().st_size>8*1024*1024:return {}
        data=json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(data,dict):return {}
        expected={'format':FORMAT,'sample_id':manifest['sample_id'],'version':manifest['version'],
                  'source_hash':item['sha256'],'parser_fingerprint':fingerprint}
        if any(data.get(key)!=value for key,value in expected.items()):return {}
        pages=data['pages']
        if not isinstance(pages,list) or len(pages)>item['page_count'] or payload_digest(pages)!=data['payload_sha256']:return {}
        found={}
        for page in pages:
            if not reusable_sample_page(page,accepted_versions):return {}
            index=page['page_index']
            if index>=item['page_count'] or index in found:return {}
            found[index]=page
        return found
    except (OSError,ValueError,KeyError,TypeError):
        return {}


def reviewed_document_pages(conn,document,fingerprint,accepted_versions):
    """A matching hash alone never authorizes shared recognition for ordinary files."""
    from services.judge_demo.app import judge_upload_allowed,sample_manifest
    case=conn.execute('''SELECT c.created_by,c.data_origin,c.source_ref,c.user_context FROM cases c
        JOIN consent_purposes p ON p.consent_id=c.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE c.case_id=%s''',
                      (document['case_id'],)).fetchone()
    if not case or case['data_origin']!='official_deidentified' or (case['user_context'] or {}).get('judge_demo') is not True:
        return {}
    try:
        if not judge_upload_allowed(conn,case['created_by'],SimpleNamespace(**case)):return {}
        context=case['user_context']
        directory,manifest=sample_manifest(context.get('sample_version'),context.get('sample_id'))
        item=next((item for item in manifest['documents'] if item['sha256']==document['source_hash']),None)
        if item is None:return {}
        original=directory/item['file']
        if hashlib.sha256(original.read_bytes()).hexdigest()!=item['sha256']:return {}
        prepared=published_sample_pages(manifest,item)
        if prepared:return prepared
        legacy=read_sample_pages(manifest,item,fingerprint,accepted_versions)
        from . import product_extraction as product
        return {i:p for i,p in legacy.items() if not product.enabled() or prepared_page_compatible(p)}
    except (HTTPException,OSError,ValueError,KeyError,TypeError):
        return {}
