"""Bind reviewed claim-specific OCR selections to current-run excerpt evidence."""
import copy,hashlib,json,math
from uuid import UUID,uuid5
from .judge_narrative_cache import source_key
from .parse_cache import payload_digest

VERSION='citation-excerpt-v1'


def local_box(box):
    return (isinstance(box,(list,tuple)) and len(box)==4
        and all(isinstance(v,(int,float)) and math.isfinite(v) for v in box)
        and 0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1
        and box[3]-box[1]<=.18 and (box[2]-box[0])*(box[3]-box[1])<=.15)


def locator(page,row):
    start,end=row['text_start'],row['text_end'];text=row['text_value'] or ''
    if (not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(page['text_value'])
        or page['text_value'][start:end]!=text or not local_box(row.get('bbox'))):
        raise ValueError('CITATION_EXCERPT_NOT_EXACT')
    return {'page_key':source_key(page),'start':start,'end':end,'text_sha256':hashlib.sha256(text.encode()).hexdigest()}


def page_identity(row):
    return tuple(str(row[k]) for k in ('document_id','document_version','page_index','source_hash','parser_version'))


def load_sources(conn,run_id,case_id):
    from .page_sources import VERSION as PAGE
    rows=conn.execute('SELECT * FROM evidence WHERE run_id=%s AND case_id=%s ORDER BY document_id,page_index,text_start,evidence_id',(run_id,case_id)).fetchall()
    pages=[r for r in rows if r['extraction_method']==PAGE]
    grains=[r for r in rows if r['extraction_method'] not in {PAGE,VERSION,'product-document-c-v1'} and local_box(r.get('bbox'))]
    return pages,grains


def resolve(draft,plan,pages,grains):
    if plan.get('version')!=VERSION or plan.get('review_passed') is not True:raise ValueError('CITATION_EXCERPTS_UNREVIEWED')
    if len(plan['citations'])!=len(draft['citations']):raise ValueError('CITATION_EXCERPT_COUNT')
    by_identity={page_identity(p):p for p in pages};by_key={source_key(p):p for p in pages};available={}
    for row in grains:
        page=by_identity.get(page_identity(row))
        if page:
            try:available[payload_digest(locator(page,row))]=row
            except ValueError:pass
    result=copy.deepcopy(draft);created=[]
    for citation,selection in zip(result['citations'],plan['citations']):
        if citation['quote']!=selection['quote']:raise ValueError('CITATION_EXCERPT_ANCHOR_CHANGED')
        refs=[r for r in citation['source_refs'] if not any(str(p['evidence_id'])==r for p in pages)]
        selected={}
        for loc in selection['sources']:
            row=available.get(payload_digest(loc));page=by_key.get(loc['page_key'])
            if not row or not page:raise ValueError('CITATION_EXCERPT_SOURCE_CHANGED')
            selected.setdefault(loc['page_key'],[]).append(row)
        if not selected and not refs and selection.get('omit') is not True:raise ValueError('CITATION_EXCERPT_MISSING')
        for key,chosen in selected.items():
            page=by_key[key];chosen=sorted({str(r['evidence_id']):r for r in chosen}.values(),key=lambda r:r['text_start'])
            groups=[]
            for row in chosen:
                if groups:
                    start,end=groups[-1][0]['text_start'],row['text_end']
                    between=[r for r in grains if page_identity(r)==page_identity(page) and r['text_start']>=start and r['text_end']<=end]
                    box=[min(r['bbox'][0] for r in between),min(r['bbox'][1] for r in between),max(r['bbox'][2] for r in between),max(r['bbox'][3] for r in between)]
                    exact='\n'.join(r['text_value'] for r in sorted(between,key=lambda r:r['text_start']))
                    if end-start<=360 and local_box(box) and page['text_value'][start:end]==exact:
                        groups[-1]=between;continue
                groups.append([row])
            for group in groups:
                start,end=group[0]['text_start'],group[-1]['text_end'];text=page['text_value'][start:end]
                box=[min(r['bbox'][0] for r in group),min(r['bbox'][1] for r in group),max(r['bbox'][2] for r in group),max(r['bbox'][3] for r in group)]
                if not local_box(box) or not text or len(text)>360:raise ValueError('CITATION_EXCERPT_TOO_BROAD')
                row={**page,'evidence_id':uuid5(UUID(str(page['evidence_id'])),VERSION+':'+str(start)+':'+str(end)),
                    'text_start':start,'text_end':end,'text_value':text,'bbox':box,'extraction_method':VERSION}
                created.append(row);refs.append(str(row['evidence_id']))
        citation['source_refs']=list(dict.fromkeys(refs))
    result['citations']=[c for c in result['citations'] if c['source_refs']]
    from .inline_citations import canonical_analysis_citations
    return canonical_analysis_citations(result,{str(r['evidence_id']):str(r['evidence_id']) for r in created},draft.get('knowledge_refs',[])),created


def save_excerpts(conn,rows):
    for row in {str(r['evidence_id']):r for r in rows}.values():
        conn.execute('''INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,page_index,
            text_start,text_end,text_value,bbox,extraction_method,source_hash,parser_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s) ON CONFLICT(evidence_id) DO NOTHING''',
            tuple(row[k] for k in ('evidence_id','run_id','case_id','document_id','document_version','page_index','text_start','text_end','text_value'))+
            (json.dumps(row['bbox']),row['extraction_method'],row['source_hash'],row['parser_version']))


def bind_prepared(conn,run_id,case_id,draft,variant):
    plan=variant.get('citation_spans')
    if not plan:raise ValueError('CITATION_EXCERPTS_UNPREPARED')
    pages,grains=load_sources(conn,run_id,case_id)
    reply,created=resolve(draft,plan,pages,grains)
    save_excerpts(conn,created)
    return reply,created
