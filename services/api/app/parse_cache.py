"""Per-document page checkpoints. Reuse recognition, never report conclusions or evidence IDs."""
import hashlib
import json

def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def cacheable(page):
    if not isinstance(page,dict) or not isinstance(page.get('metadata'),dict):return False
    quality=page['metadata'].get('photo_quality',{})
    if not isinstance(quality,dict):return False
    return (isinstance(page,dict) and page.get('status')=='parsed'
        and isinstance(page.get('text'),str) and bool(page['text'].strip())
        and isinstance(page.get('page_index'),int) and page['page_index']>=0
        and isinstance(page.get('blocks'),list) and bool(page['blocks'])
        and isinstance(page.get('metadata'),dict) and not page.get('requires_ocr',True)
        and not quality.get('needs_reupload')
        and all(isinstance(block,dict) and all(key in block for key in ('type','order','text','metadata')) for block in page['blocks'])
        and all(key in page for key in ('content_hash','parser_version','page_kind','requires_vision')))

def require_parse_scope(conn,run):
    allowed=conn.execute('''SELECT 1 FROM analysis_runs r JOIN cases c ON c.case_id=r.case_id
        JOIN consent_purposes p ON p.consent_id=c.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE r.run_id=%s AND r.case_id=%s AND r.lease_token=%s AND r.status='running'
        FOR SHARE OF r,c,p''',(run['run_id'],run['case_id'],run['lease_token'])).fetchone()
    if not allowed:raise RuntimeError('ANALYSIS_PARSE_UNAUTHORIZED')

def cached_pages(conn,document,fingerprint,accepted_versions,routing_version,pipeline_version):
    rows=conn.execute('''SELECT page_index,page_payload,payload_sha256 FROM parsed_page_cache
        WHERE document_id=%s AND document_version=%s AND source_hash=%s AND parser_fingerprint=%s
        ORDER BY page_index''',(document['document_id'],document['document_version'],document['source_hash'],fingerprint)).fetchall()
    found={}
    for row in rows:
        payload=row['page_payload']
        if cacheable(payload) and payload['page_index']==row['page_index'] and payload_digest(payload)==row['payload_sha256']:
            found[row['page_index']]=payload
    # Existing successful recognition, including a later report-generation
    # failure, can be reused on the first retry after this feature is deployed.
    legacy=conn.execute('''SELECT p.*,b.run_id FROM document_pages p JOIN LATERAL (
        SELECT b.run_id FROM page_blocks b JOIN analysis_runs r ON r.run_id=b.run_id
        WHERE b.document_id=p.document_id AND b.document_version=p.document_version
          AND b.page_index=p.page_index AND b.case_id=%s AND b.source_hash=%s
          AND b.parser_version=p.parser_version AND r.pipeline_version=%s
        ORDER BY r.created_at DESC LIMIT 1) b ON true
        WHERE p.document_id=%s AND p.document_version=%s AND p.routing_version=%s
          AND p.parser_version=ANY(%s) AND p.status='parsed' ''',
        (document['case_id'],document['source_hash'],pipeline_version,document['document_id'],
         document['document_version'],routing_version,list(accepted_versions))).fetchall()
    for page in legacy:
        if page['page_index'] in found:continue
        blocks=conn.execute('''SELECT block_type,reading_order,text_content,bbox,metadata FROM page_blocks
            WHERE run_id=%s AND document_id=%s AND document_version=%s AND page_index=%s
              AND case_id=%s AND source_hash=%s AND parser_version=%s ORDER BY reading_order''',
            (page['run_id'],document['document_id'],document['document_version'],page['page_index'],
             document['case_id'],document['source_hash'],page['parser_version'])).fetchall()
        payload={'page_index':page['page_index'],'page_kind':page['page_kind'],'text':page['text_content'],
            'content_hash':page['content_hash'],'status':page['status'],'requires_ocr':page['requires_ocr'],
            'requires_vision':page['requires_vision'],'parser_version':page['parser_version'],
            'metadata':page['structure_metadata'],'blocks':[{'type':block['block_type'],'order':block['reading_order'],
                'text':block['text_content'],'bbox':block['bbox'],'metadata':block['metadata']} for block in blocks]}
        if cacheable(payload):found[page['page_index']]=payload
    return found

def save_page(conn,document,fingerprint,page):
    if not cacheable(page):return
    conn.execute('''INSERT INTO parsed_page_cache(document_id,document_version,source_hash,parser_fingerprint,
        page_index,page_payload,payload_sha256) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
        ON CONFLICT (document_id,document_version,source_hash,parser_fingerprint,page_index)
        DO UPDATE SET page_payload=excluded.page_payload,payload_sha256=excluded.payload_sha256''',
        (document['document_id'],document['document_version'],document['source_hash'],fingerprint,
         page['page_index'],json.dumps(page,ensure_ascii=False),payload_digest(page)))
