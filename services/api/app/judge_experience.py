"""Explicit fixed-sample report experience; ordinary reports and follow-ups stay live."""
import copy,hashlib,json,os
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .parse_cache import payload_digest
from .judge_narrative_cache import source_key

FORMAT='judge-report-experience-v1'
DURATION_MS=8000


def question_key(text):
    return payload_digest(text.strip().removesuffix('（重新分析当前材料）').strip())


def version_identity(manifest=None):
    from .conversation_agent import SYSTEM,ANALYSIS_INSTRUCTION,ANALYSIS_PROMPT_VERSION
    from .report_llm import PROMPT_VERSION
    from .report_builder import POLICY_VERSION
    from .knowledge_assembler import KnowledgeAssembler
    from .judge_sample_cache import published_path,extraction_identity
    return payload_digest({'format':FORMAT,'instructions':[SYSTEM,ANALYSIS_INSTRUCTION],
        'analysis':ANALYSIS_PROMPT_VERSION,'report':PROMPT_VERSION,'policy':POLICY_VERSION,
        'knowledge':KnowledgeAssembler().knowledge_version,'extraction':extraction_identity(),
        'prepared_materials':hashlib.sha256(published_path(manifest).read_bytes()).hexdigest(),
        'provider':os.getenv('LLM_PROVIDER'),'model':os.getenv('LLM_MODEL_ID'),
        'base':os.getenv('LLM_BASE_URL')})


def artifact_path(manifest=None,*,versioned=False):
    root=Path(os.getenv('ZHONGAN_JUDGE_RECOGNITION_ROOT','/home/ubuntu/zhongan-data/judge-recognition'))
    if manifest:
        scoped=root/('report-experience-'+payload_digest({k:manifest[k] for k in ('sample_id','version')})+'.json')
        if versioned or scoped.exists():return scoped
    return root/'report-experience.json'


def eligible_context(context,questions,memory,patient_context,allowed):
    return (isinstance(context,dict) and context.get('judge_demo') is True
        and not set(context)-{'judge_demo','sample_id','sample_version','notice','verification'}
        and context.get('verification','latency-benchmark')=='latency-benchmark'
        and 1<=len(questions)<=20 and all(question_key(q) in allowed for q in questions)
        and not memory and not patient_context)


def read_bundle(manifest=None):
    try:
        path=artifact_path(manifest)
        if path.is_symlink() or path.stat().st_size>4*1024*1024:return None
        payload=json.loads(path.read_text(encoding='utf8'))
        if payload.get('format')!=FORMAT or payload.get('identity')!=version_identity(manifest):return None
        data=payload['data']
        if manifest and (data.get('sample_id'),data.get('sample_version'))!=(manifest['sample_id'],manifest['version']):return None
        if payload_digest(data)!=payload['payload_sha256'] or not 2<=len(data['variants'])<=5:return None
        if any(v.get('preparation_review')!={'source_review_passed':True,'quality_passed':True} for v in data['variants']):return None
        return data
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return None


def select_variant(bundle,run_id):
    return bundle['variants'][int(hashlib.sha256(str(run_id).encode()).hexdigest(),16)%len(bundle['variants'])]


def check_scope(conn,run,bundle,rows):
    from .conversation_repository import require_conversation,get_patient_context
    from .judge_sample_cache import reviewed_document_pages
    from .worker import recognition_profile
    from services.judge_demo.app import sample_manifest
    case=conn.execute('SELECT created_by,user_context FROM cases WHERE case_id=%s',(run['case_id'],)).fetchone()
    chat=(run.get('context_snapshot') or {}).get('chat')
    if chat:
        # The worker can claim the queued run before its initiating turn finishes.
        # Bind to the run's frozen anchor rather than racing the tool-event write.
        conversation=conn.execute('''SELECT v.conversation_id FROM conversations v JOIN conversation_turns t ON t.conversation_id=v.conversation_id
            WHERE v.case_id=%s AND v.actor_id=%s AND v.conversation_id=%s AND t.turn_id=%s
            AND t.input_kind='user' AND t.status IN ('running','completed')''',
            (run['case_id'],case['created_by'],chat['conversation_id'],chat['anchor_turn_id'])).fetchone()
    else:
        conversation=conn.execute('''SELECT v.conversation_id FROM conversations v JOIN conversation_turns t ON t.conversation_id=v.conversation_id
            WHERE v.case_id=%s AND v.actor_id=%s AND t.status='completed' AND t.tool_events @> %s::jsonb
            ORDER BY t.created_at DESC LIMIT 1''',
            (run['case_id'],case['created_by'],json.dumps([{'tool':'start_analysis','run_id':str(run['run_id'])}]))).fetchone()
    if not conversation:return None
    cid=conversation['conversation_id'];require_conversation(conn,case['created_by'],cid)
    turns=conn.execute("SELECT question,attachments FROM conversation_turns WHERE conversation_id=%s AND input_kind='user' ORDER BY created_at LIMIT 21",(cid,)).fetchall()
    if not eligible_context(case['user_context'],[t['question'] for t in turns],
        (run.get('context_snapshot') or {}).get('memory'),get_patient_context(conn,case['created_by'],cid),bundle['question_keys']):return None
    if any(a.get('kind')=='chat_attachment' for t in turns for a in (t['attachments'] or [])):return None
    context=case['user_context']
    _,manifest=sample_manifest(context['sample_version'],context['sample_id'])
    if (manifest['sample_id'],manifest['version'])!=(bundle['sample_id'],bundle['sample_version']):return None
    documents=conn.execute('SELECT * FROM documents WHERE case_id=%s ORDER BY document_id',(run['case_id'],)).fetchall()
    if sorted(d['source_hash'] for d in documents)!=sorted(bundle['source_hashes']):return None
    profile,versions=recognition_profile('document-parser-v1')
    if sum(len(reviewed_document_pages(conn,d,profile,versions)) for d in documents)!=manifest['page_count']:return None
    if sorted(source_key(r) for r in rows)!=bundle['page_keys']:return None
    return {'actor_id':case['created_by'],'conversation_id':cid}


def resolve_knowledge(variant,rows):
    from .knowledge_retrieval import KnowledgeRetriever
    versions=variant['knowledge_versions']
    found=KnowledgeRetriever().resolve_references(list(versions),case_text='\n'.join(r['text_value'] for r in rows))['results'] if versions else []
    if {r['entry_id']:r['version'] for r in found}!=versions:return None
    return found


def read_worker_models(conn,run,parsed_documents,narrative_sources):
    try:
        from services.judge_demo.app import sample_manifest
        context=(run.get('context_snapshot') or {}).get('case_user_context') or {}
        if context.get('judge_demo') is not True:return None
        _,manifest=sample_manifest(context.get('sample_version'),context.get('sample_id'))
        bundle=read_bundle(manifest)
        if not bundle:return None
        rows=[{'source_hash':d['source_hash'],'page_index':p['page_index'],'parser_version':p['parser_version'],
            'text_value':narrative_sources[(d['document_id'],d['document_version'],p['page_index'])][0]['text']}
            for d,pages in parsed_documents for p in pages]
        if not check_scope(conn,run,bundle,rows):return None
        variant=select_variant(bundle,run['run_id']);knowledge=resolve_knowledge(variant,rows)
        if knowledge is None:return None
        from .report_llm import StructuredDraftReport
        report=copy.deepcopy(variant['report'])
        report['draft']=StructuredDraftReport.model_validate(report['draft']).model_dump(mode='json')
        report['reference_knowledge']=knowledge
        report['usage_metadata']={**report.get('usage_metadata',{}),'patient_analysis_mode':'prepared_demo'}
        from .insight_llm import SemanticInsights
        insights=copy.deepcopy(variant['insights'])
        SemanticInsights.model_validate({'candidates':insights['candidates']})
        return {'report':report,'insights':insights,'variant':variant['id']}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,HTTPException):return None


def bind_draft(variant,rows):
    from .conversation_agent import AnalysisWireReply
    from .inline_citations import canonical_analysis_citations
    draft=copy.deepcopy(variant['draft']);mapping={source_key(r):str(r['evidence_id']) for r in rows}
    draft['evidence_refs']=[mapping[r] for r in draft['evidence_refs']]
    for citation in draft['citations']:citation['source_refs']=[mapping.get(r,r) for r in citation['source_refs']]
    draft=canonical_analysis_citations(draft,{r:r for r in mapping.values()},list(variant['knowledge_versions']))
    return AnalysisWireReply.model_validate(draft)


def prepared_answer(tools,run_id):
    if run_id is None:return None
    try:
        from .material_report import get_material_report
        report=get_material_report(tools.conn,tools.actor_id,tools.conversation_id)
        if report.get('status')!='available' or report.get('run_id')!=str(run_id):return None
        run=tools.conn.execute('SELECT * FROM analysis_runs WHERE run_id=%s',(run_id,)).fetchone()
        from services.judge_demo.app import sample_manifest
        context=(run.get('context_snapshot') or {}).get('case_user_context') or {}
        if context.get('judge_demo') is not True:return None
        _,manifest=sample_manifest(context.get('sample_version'),context.get('sample_id'))
        bundle=read_bundle(manifest)
        if not bundle:return None
        if not (run['stage_results'].get('performance') or {}).get('judge_experience'):return None
        from .page_sources import VERSION
        rows=tools.conn.execute('SELECT evidence_id,source_hash,page_index,text_value,parser_version FROM evidence WHERE run_id=%s AND case_id=%s AND extraction_method=%s',
            (run_id,run['case_id'],VERSION)).fetchall()
        checked=check_scope(tools.conn,run,bundle,rows)
        if not checked or checked['actor_id']!=tools.actor_id or checked['conversation_id']!=tools.conversation_id:return None
        variant=select_variant(bundle,run_id);knowledge=resolve_knowledge(variant,rows)
        if knowledge is None:return None
        reply=bind_draft(variant,rows)
        tools.evidence_ids.update(str(r['evidence_id']) for r in rows)
        tools.knowledge_sources.update({r['entry_id']:r for r in knowledge})
        tools.validate_reply(reply)
        from .conversation_agent import ANALYSIS_PROMPT_VERSION
        answer={**reply.model_dump(mode='json'),'prompt_version':ANALYSIS_PROMPT_VERSION,
            'guidance_delivery':{'status':'passed'},'judge_experience':{'mode':'prepared_sample','duration_ms':DURATION_MS},
            'knowledge_sources':knowledge,'performance':{'model_calls':0,'review_calls':0,'draft_reused':True,
                'prepared_source_review':True,'source_read_complete':True,'partial_delivery':False}}
        return answer,[{'tool':'read_materials','status':'available'},{'tool':'prepare_sample_report','status':'completed'}]
    except (OSError,ValueError,TypeError,KeyError,AttributeError,HTTPException):return None


def prepare_variant(reply,rows,report,insights,variant_id,knowledge_sources):
    """Accept only completed independently reviewed prose and keep no case-specific IDs."""
    from .conversation_agent import AnalysisWireReply
    from .inline_citations import canonical_analysis_citations
    perf=reply.get('performance') or {}
    if (not perf.get('source_read_complete') or perf.get('review_calls',0)<1 or perf.get('partial_delivery') is not False
        or reply.get('guidance_delivery',{}).get('status')!='passed'):raise ValueError('UNVERIFIED_EXPERIENCE_VARIANT')
    draft=AnalysisWireReply.model_validate({k:reply[k] for k in AnalysisWireReply.model_fields if k in reply}).model_dump(mode='json')
    if draft['history_refs'] or draft['patient_updates'] or draft['memory_suggestions']:raise ValueError('PERSONAL_EXPERIENCE_VARIANT')
    mapping={str(r['evidence_id']):source_key(r) for r in rows}
    draft=canonical_analysis_citations(draft,{r:r for r in mapping},draft['knowledge_refs'])
    if not draft['evidence_refs'] or not draft['citations']:raise ValueError('UNSOURCED_EXPERIENCE_VARIANT')
    draft['evidence_refs']=[mapping[r] for r in draft['evidence_refs']]
    for citation in draft['citations']:citation['source_refs']=[mapping.get(r,r) for r in citation['source_refs']]
    # Model document aliases are not user-statement references. Exact quote binding runs afresh in Worker.
    report=copy.deepcopy(report)
    if report.get('status')!='completed':raise ValueError('INCOMPLETE_EXPERIENCE_REPORT')
    for section in report['draft']['sections']:
        for claim in section['claims']:
            if claim['claim_type']=='patient_statement':raise ValueError('PERSONAL_EXPERIENCE_REPORT')
            claim['source_refs']=[]
    for action in report['draft'].get('actions',[]):action['source_refs']=[]
    report['draft']['patient_analysis']=None;report['raw_output']=None;report['repaired_output']=None
    refs=set(draft['knowledge_refs'])|{r for s in report['draft']['sections'] for c in s['claims'] for r in c.get('knowledge_refs',[])}
    sources={r['entry_id']:r for r in knowledge_sources}
    insights=copy.deepcopy(insights);insights['raw_output']=None
    return {'id':variant_id,'draft':draft,'report':report,'insights':insights,
        'knowledge_versions':{r:sources[r]['version'] for r in refs},'preparation_review':{'source_review_passed':True,'quality_passed':True}}


def publish_bundle(manifest,questions,rows,variants,*,versioned=False):
    if len({v['id'] for v in variants})!=len(variants) or not 2<=len(variants)<=5:raise ValueError('EXPERIENCE_VARIANT_COUNT')
    if any(v.get('preparation_review')!={'source_review_passed':True,'quality_passed':True} for v in variants):raise ValueError('UNVERIFIED_EXPERIENCE_VARIANT')
    data={'sample_id':manifest['sample_id'],'sample_version':manifest['version'],
        'source_hashes':sorted(d['sha256'] for d in manifest['documents']),
        'page_keys':sorted(source_key(r) for r in rows),'question_keys':sorted({question_key(q) for q in questions}),
        'variants':variants}
    target=artifact_path(manifest,versioned=versioned);temp=target.with_suffix('.tmp-'+uuid4().hex)
    try:
        with temp.open('x',encoding='utf8') as stream:
            os.chmod(temp,0o600);json.dump({'format':FORMAT,'identity':version_identity(manifest),'data':data,'payload_sha256':payload_digest(data)},stream,ensure_ascii=False,separators=(',',':'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:
        if temp.exists():temp.unlink()
