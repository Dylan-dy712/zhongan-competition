"""Prepared sample drafts; every delivered reuse still gets current-source review."""
import copy,json,os
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .parse_cache import payload_digest

FORMAT='reviewed-sample-patient-draft-v1'
QUESTIONS={'请分析本次上传材料，整理就医经过、费用与待补充信息。',
           '请结合本次实际提交的材料，解释主要诊断、治疗经过、费用含义和康复复诊安排。'}


def generic_context(context,questions,recall,memory,patient_context):
    allowed={'judge_demo','sample_id','sample_version','notice','verification'}
    return (isinstance(context,dict) and context.get('judge_demo') is True and not set(context)-allowed
        and context.get('verification','latency-benchmark')=='latency-benchmark'
        and len(questions)==1 and questions[0] in QUESTIONS and not memory and not patient_context)


def source_key(row):
    return payload_digest({key:row[key] for key in ('source_hash','page_index','text_value','parser_version')})


def scope(conn,actor_id,conversation_id,run_id):
    from .conversation_repository import require_conversation,get_patient_context
    from .judge_sample_cache import reviewed_document_pages
    from .worker import recognition_profile
    from services.judge_demo.app import sample_manifest
    current=require_conversation(conn,actor_id,conversation_id)
    case=conn.execute('SELECT user_context FROM cases WHERE case_id=%s',(current['case_id'],)).fetchone()
    run=conn.execute('SELECT context_snapshot FROM analysis_runs WHERE case_id=%s AND run_id=%s',
                     (current['case_id'],run_id)).fetchone()
    turns=conn.execute("SELECT question,attachments FROM conversation_turns WHERE conversation_id=%s AND input_kind='user' ORDER BY created_at LIMIT 2",(conversation_id,)).fetchall()
    if not run or not generic_context(case['user_context'],[t['question'] for t in turns],current['recall_enabled'],
        (run['context_snapshot'] or {}).get('memory'),get_patient_context(conn,actor_id,conversation_id)):return None
    if any(a.get('kind')=='chat_attachment' for turn in turns for a in (turn['attachments'] or [])):return None
    context=case['user_context'];_,manifest=sample_manifest(context['sample_version'],context['sample_id'])
    documents=conn.execute('SELECT * FROM documents WHERE case_id=%s ORDER BY document_id',(current['case_id'],)).fetchall()
    if sorted(doc['source_hash'] for doc in documents)!=sorted(item['sha256'] for item in manifest['documents']):return None
    profile,versions=recognition_profile('document-parser-v1')
    pages=sum(len(reviewed_document_pages(conn,doc,profile,versions)) for doc in documents)
    if pages!=manifest['page_count']:return None
    from .page_sources import VERSION
    rows=conn.execute('SELECT evidence_id,source_hash,page_index,text_value,parser_version FROM evidence WHERE case_id=%s AND run_id=%s AND extraction_method=%s',
                      (current['case_id'],run_id,VERSION)).fetchall()
    if len(rows)!=pages or len({source_key(row) for row in rows})!=pages:return None
    return {'sample_id':manifest['sample_id'],'version':manifest['version'],'rows':rows}


def identity(checked):
    from .conversation_agent import ANALYSIS_INSTRUCTION,ANALYSIS_PROMPT_VERSION,SYSTEM
    from .guidance_quality import GUIDANCE_INSTRUCTION
    from .report_llm import PROMPT_VERSION
    from .knowledge_assembler import KnowledgeAssembler
    return payload_digest({'format':FORMAT,'sample_id':checked['sample_id'],'version':checked['version'],
        'sources':sorted(source_key(row) for row in checked['rows']),
        'analysis_prompt':ANALYSIS_PROMPT_VERSION,'report_prompt':PROMPT_VERSION,
        'instructions':payload_digest([SYSTEM,ANALYSIS_INSTRUCTION,GUIDANCE_INSTRUCTION]),
        'knowledge':KnowledgeAssembler().knowledge_version,
        'provider':os.environ.get('LLM_PROVIDER','openai_compatible'),'model':os.environ.get('LLM_MODEL_ID',''),
        'endpoint':os.environ.get('LLM_BASE_URL','').rstrip('/')})


def artifact_path(key):
    return Path(os.getenv('ZHONGAN_JUDGE_RECOGNITION_ROOT','/home/ubuntu/zhongan-data/judge-recognition'))/'narrative'/(key+'.json')


def write_prepared(conn,actor_id,conversation_id,run_id,reply,knowledge_sources):
    checked=scope(conn,actor_id,conversation_id,run_id)
    perf=reply.get('performance') or {}
    if (not checked or not perf.get('source_read_complete') or perf.get('review_calls',0)<1
        or perf.get('partial_delivery') is not False or reply.get('guidance_delivery',{}).get('status')!='passed'
        or len(reply.get('text',''))<650):raise ValueError('SAMPLE_DRAFT_NOT_VERIFIED')
    from .conversation_agent import AnalysisWireReply
    draft=AnalysisWireReply.model_validate({key:copy.deepcopy(reply[key]) for key in AnalysisWireReply.model_fields if key in reply}).model_dump(mode='json')
    if draft['history_refs'] or draft['patient_updates'] or draft['memory_suggestions']:raise ValueError('PERSONAL_DRAFT_NOT_CACHEABLE')
    mapped={str(row['evidence_id']):source_key(row) for row in checked['rows']}
    from .inline_citations import canonical_analysis_citations
    draft=canonical_analysis_citations(draft,{ref:ref for ref in mapped},draft['knowledge_refs'])
    if not draft['evidence_refs'] or not draft['citations']:raise ValueError('SAMPLE_DRAFT_SOURCE_INVALID')
    for ref in draft['evidence_refs']:
        if ref not in mapped:raise ValueError('SAMPLE_DRAFT_SOURCE_INVALID')
    draft['evidence_refs']=[mapped[ref] for ref in draft['evidence_refs']]
    for citation in draft['citations']:
        citation['source_refs']=[mapped[ref] if ref in mapped else ref for ref in citation['source_refs']]
    versions={ref:knowledge_sources[ref]['version'] for ref in draft['knowledge_refs']}
    data={'draft':draft,'knowledge_versions':versions,'guidance_delivery':{'status':'passed'}}
    key=identity(checked);target=artifact_path(key);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(target.parent,0o700)
    payload={'format':FORMAT,'identity':key,'data':data,'payload_sha256':payload_digest(data)}
    temporary=target.with_suffix('.tmp-'+uuid4().hex)
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            os.chmod(temporary,0o600);json.dump(payload,stream,ensure_ascii=False,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    return key


def read_prepared(conn,actor_id,conversation_id,run_id):
    try:
        checked=scope(conn,actor_id,conversation_id,run_id)
        if not checked:return None
        key=identity(checked);path=artifact_path(key)
        if path.is_symlink() or path.stat().st_size>2*1024*1024:return None
        payload=json.loads(path.read_text(encoding='utf-8'))
        if payload['format']!=FORMAT or payload['identity']!=key or payload_digest(payload['data'])!=payload['payload_sha256']:return None
        data=payload['data'];draft=copy.deepcopy(data['draft'])
        from .knowledge_retrieval import KnowledgeRetriever
        found=KnowledgeRetriever().resolve_references(draft['knowledge_refs'],case_text='\n'.join(row['text_value'] for row in checked['rows']))['results'] if draft['knowledge_refs'] else []
        if {item['entry_id']:item['version'] for item in found}!=data['knowledge_versions']:return None
        mapped={source_key(row):str(row['evidence_id']) for row in checked['rows']}
        draft['evidence_refs']=[mapped[ref] for ref in draft['evidence_refs']]
        for citation in draft['citations']:
            citation['source_refs']=[mapped.get(ref,ref) for ref in citation['source_refs']]
        from .conversation_agent import AnalysisWireReply
        draft=AnalysisWireReply.model_validate(draft).model_dump(mode='json')
        return {'draft':draft,'guidance_delivery':data['guidance_delivery']}
    except (OSError,ValueError,KeyError,TypeError,HTTPException):return None
