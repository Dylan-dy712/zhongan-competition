"""Page-level narrative sources alongside unchanged granular fact evidence."""
from uuid import uuid4

VERSION='reviewed-sample-page-v1'


def narrative_page_source(document,page,readable):
    # Use only the same readable evidence already prepared for facts. Excluded
    # OCR blocks never enter this source; original block evidence stays intact.
    text='\n'.join(item['text'] for item in readable if item.get('text'))
    if not text:return None
    return {'evidence_id':uuid4(),'document_id':document['document_id'],
            'document_version':document['document_version'],'page_index':page['page_index'],
            'start':0,'end':len(text),'text':text,'bbox':None,'extraction_method':VERSION}


def readable_materials(conn,case_id,run_id,pattern,page_size,offset,balanced):
    order='source_index,document_id' if balanced else 'document_id,page_index,text_start,evidence_id'
    return conn.execute('''SELECT evidence_id,document_id,page_index,text_value AS text FROM (
        SELECT *,row_number() OVER(PARTITION BY document_id ORDER BY page_index,text_start,evidence_id) AS source_index
        FROM evidence WHERE case_id=%s AND run_id=%s AND text_value ILIKE %s
          AND (extraction_method=%s OR NOT EXISTS (
            SELECT 1 FROM evidence pages WHERE pages.case_id=%s AND pages.run_id=%s
              AND pages.extraction_method=%s))) AS sources
        ORDER BY '''+order+' LIMIT %s OFFSET %s',
        (case_id,run_id,pattern,VERSION,case_id,run_id,VERSION,page_size+1,offset)).fetchall()
