"""Authorized, reversible record grouping over immutable analysis cases.

GET never calls a model. New successful analyses enqueue a separate best-effort job;
organization failure cannot fail, rewrite or publish the original medical report.
"""
import json
import re
import time
from uuid import NAMESPACE_URL,UUID,uuid4,uuid5

from .repository import AccessDenied,connect,run_input_hash
from .report_context import context_sources
from .medical_record_model import assess_record,PROMPT_VERSION,_dates,_identifiers

class StaleRecord(Exception):pass

def _default_id(actor,case):return uuid5(NAMESPACE_URL,f'zhongan:medical-record:{actor}:{case}')

def _lock(conn,actor,subject):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'medical-record:{actor}:{subject}',))

def _require_subject(conn,actor,subject):
    if not conn.execute('''SELECT 1 FROM actor_subject_access a JOIN actors ac USING(actor_id)
        WHERE a.actor_id=%s AND a.subject_id=%s AND a.can_read_case=true AND ac.active=true''',(actor,subject)).fetchone():raise AccessDenied()

def _cases(conn,actor,subject):
    _require_subject(conn,actor,subject)
    return conn.execute('''SELECT c.*,greatest(c.created_at,max(v.updated_at)) AS updated_at
        FROM cases c JOIN conversations v ON v.case_id=c.case_id AND v.actor_id=%s
        JOIN actors ac ON ac.actor_id=v.actor_id AND ac.active=true
        JOIN actor_subject_access a ON a.actor_id=v.actor_id AND a.subject_id=c.subject_id AND a.can_read_case=true
        JOIN consent_purposes p ON p.consent_id=c.consent_id AND p.purpose='case_guidance' AND p.status='active'
            AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE c.created_by=%s AND c.subject_id=%s
            AND EXISTS(SELECT 1 FROM documents d WHERE d.case_id=c.case_id)
        GROUP BY c.case_id ORDER BY updated_at DESC,c.case_id''',(actor,actor,subject)).fetchall()

def _snapshot(conn,case):
    run=conn.execute('SELECT * FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC,run_id DESC LIMIT 1',(case['case_id'],)).fetchone()
    if not run or run['status'] not in ('completed','waiting_review'):return None
    docs=conn.execute('''SELECT document_id,document_version,source_hash FROM documents d WHERE case_id=%s
        AND NOT EXISTS(SELECT 1 FROM document_replacements r WHERE r.old_document_id=d.document_id) ORDER BY document_id''',(case['case_id'],)).fetchall()
    actual=[{**doc,'document_id':str(doc['document_id'])} for doc in docs]
    if sorted(run['document_versions'],key=lambda d:(d['document_id'],d['document_version']))!=actual:return None
    if run_input_hash(actual,run['pipeline_version'],run.get('context_snapshot'))!=run['input_hash']:return None
    try:context_sources(conn,run)
    except ValueError:return None
    sources=conn.execute('''SELECT evidence_id,text_value AS text,document_id,page_index FROM evidence
        WHERE run_id=%s AND case_id=%s AND text_value IS NOT NULL ORDER BY document_id,page_index,text_start,evidence_id''',(run['run_id'],case['case_id'])).fetchall()
    return {'run':run,'sources':sources}

def _fallback_profile(snapshot):
    """Legacy records remain useful before optional AI organization, without guessing diagnoses."""
    if not snapshot:return {}
    fields={}
    labels={'diagnosis':r'(?:出院诊断|入院诊断|临床诊断|诊断)[：:]\s*([^\n。；]+)',
        'hospital':r'(?:就诊医院|医疗机构名称|医院名称|医院)[：:]\s*([^\n。；]+)',
        'period':r'(?:就诊日期|入院日期|入院时间|住院时间)[：:]\s*([^\n。；]+)',
        'kind':r'(门诊病历|急诊病历|出院记录|出院小结|住院病历)'}
    for source in snapshot['sources']:
        for key,pattern in labels.items():
            match=re.search(pattern,source['text'])
            if key not in fields and match and 0<len(match[1].strip())<=120:
                fields[key]={'value':match[1].strip(),'evidence_refs':[str(source['evidence_id'])]}
    return fields

def _valid_profile(mapping,snapshot):
    if not snapshot:return {}
    sources={str(s['evidence_id']):''.join(s['text'].split()) for s in snapshot['sources']}
    saved=(mapping.get('profile') or {}) if mapping else {}
    if mapping and mapping.get('run_id')!=snapshot['run']['run_id']:saved={}
    result={}
    for key,value in saved.items():
        if key not in {'diagnosis','hospital','period','kind','summary'} or not isinstance(value,dict):continue
        refs=value.get('evidence_refs') or [];text=value.get('value','')
        if refs and set(refs).issubset(sources) and any(''.join(text.split()) in sources[ref] for ref in refs):result[key]=value
    return {**_fallback_profile(snapshot),**result}

def _mapping(conn,case_id):return conn.execute('SELECT * FROM medical_record_cases WHERE case_id=%s',(case_id,)).fetchone()

def _ensure_case(conn,case,actor):
    old=_mapping(conn,case['case_id'])
    if old:return old
    record=_default_id(actor,case['case_id'])
    conn.execute('INSERT INTO medical_records(record_id,actor_id,subject_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(record,actor,case['subject_id']))
    return conn.execute('INSERT INTO medical_record_cases(case_id,record_id) VALUES (%s,%s) RETURNING *',(case['case_id'],record)).fetchone()

def enqueue(conn,run_id,*,retry=False):
    conn.execute('''INSERT INTO medical_record_jobs(run_id) VALUES (%s) ON CONFLICT(run_id) DO UPDATE
        SET status='queued',attempts=0,error_code=NULL,finished_at=NULL,lease_token=NULL,lease_expires_at=NULL
        WHERE %s AND medical_record_jobs.status IN ('failed','obsolete')''',(run_id,retry))

def organize(conn,actor,subject):
    queued=0
    for case in reversed(_cases(conn,actor,subject)):
        snapshot=_snapshot(conn,case)
        if not snapshot:continue
        mapping=_mapping(conn,case['case_id'])
        if mapping and mapping['run_id']==snapshot['run']['run_id'] and mapping['status']=='ready':continue
        enqueue(conn,snapshot['run']['run_id'],retry=True);queued+=1
    return {'queued_count':queued}

def list_records(conn,actor,subject):
    cases=_cases(conn,actor,subject);records={};unorganized=0
    for case in cases:
        cid=case['case_id'];mapping=_mapping(conn,cid);snapshot=_snapshot(conn,case)
        record_id=str(mapping['record_id'] if mapping else _default_id(actor,cid))
        convs=conn.execute('''SELECT conversation_id,case_id,%s::uuid AS subject_id,title,recall_enabled,report_context_enabled,
            report_context_version,created_at,updated_at FROM conversations WHERE case_id=%s AND actor_id=%s
            ORDER BY updated_at DESC,conversation_id''',(subject,cid,actor)).fetchall()
        documents=conn.execute('''SELECT source_hash FROM documents d WHERE case_id=%s
            AND NOT EXISTS(SELECT 1 FROM document_replacements r WHERE r.old_document_id=d.document_id)''',(cid,)).fetchall()
        latest=conn.execute('SELECT run_id,status FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC,run_id DESC LIMIT 1',(cid,)).fetchone()
        profile=_valid_profile(mapping,snapshot)
        status=mapping['status'] if mapping else 'pending'
        if snapshot and mapping and mapping['status']=='unavailable':unorganized+=1
        if not mapping or not snapshot or mapping['run_id']!=snapshot['run']['run_id']:
            if snapshot:unorganized+=1
            status='pending'
        item={'case_id':cid,'conversations':convs,'updated_at':case['updated_at'],'profile':profile,
            'analysis_status':latest['status'] if latest else 'not_started','document_count':len(documents),
            'organization_status':status,'version':mapping['version'] if mapping else 0,
            'relation':mapping['relation'] if mapping else 'independent','assignment_source':mapping['assignment_source'] if mapping else 'provisional',
            'proposed_record_id':str(mapping['proposed_record_id']) if mapping and mapping['proposed_record_id'] else None,
            'reason':(mapping['decision'] or {}).get('reason') if mapping and status in ('ready','needs_confirmation') else None}
        group=records.setdefault(record_id,{'record_id':record_id,'subject_id':subject,'cases':[],'updated_at':case['updated_at'],
            'related_record_ids':[],'document_hashes':set()})
        group['cases'].append(item);group['document_hashes'].update(d['source_hash'] for d in documents)
        if mapping and mapping['related_record_id']:group['related_record_ids'].append(str(mapping['related_record_id']))
    for group in records.values():
        portrait={}
        for batch in group['cases']:
            for key,value in batch['profile'].items():portrait.setdefault(key,value)
        group['portrait']=portrait
        diagnoses=list(dict.fromkeys(c['profile']['diagnosis']['value'] for c in group['cases'] if 'diagnosis' in c['profile']))
        group['title']='、'.join(diagnoses[:2])[:160] if diagnoses else '就医资料待核对'
        group['document_count']=len(group.pop('document_hashes'))
        group['conversation_count']=sum(len(c['conversations']) for c in group['cases'])
    for group in records.values():
        group['related_records']=[{'record_id':rid,'title':records[rid]['title']}
            for rid in dict.fromkeys(group.pop('related_record_ids')) if rid in records and rid!=group['record_id']]
    # Populate reverse links as well; neither direction exposes a revoked/foreign record.
    for group in records.values():
        for link in list(group['related_records']):
            other=records[link['record_id']]
            if not any(x['record_id']==group['record_id'] for x in other['related_records']):other['related_records'].append({'record_id':group['record_id'],'title':group['title']})
        for item in group['cases']:
            proposal=records.get(item['proposed_record_id'])
            item['proposal_title']=proposal['title'] if proposal and proposal!=group else None
            if not item['proposal_title']:item['proposed_record_id']=None
    processing=conn.execute('''SELECT count(*) AS n FROM medical_record_jobs j JOIN analysis_runs r USING(run_id)
        JOIN cases c ON c.case_id=r.case_id WHERE c.case_id=ANY(%s::uuid[]) AND j.status IN ('queued','running')''',([c['case_id'] for c in cases],)).fetchone()['n']
    return {'records':list(records.values()),'unorganized_count':unorganized,'processing_count':processing}

def change_assignment(conn,actor,case_id,mode,target_record_id,expected_version):
    row=conn.execute('SELECT subject_id FROM cases WHERE case_id=%s',(case_id,)).fetchone()
    if not row:raise AccessDenied()
    with conn.transaction():
        _lock(conn,actor,row['subject_id'])
        cases=_cases(conn,actor,row['subject_id']);case=next((c for c in cases if c['case_id']==case_id),None)
        if not case:raise AccessDenied()
        old=_mapping(conn,case_id)
        if (old['version'] if old else 0)!=expected_version:raise StaleRecord()
        target=None
        if mode in ('join','related'):
            candidates=[c for c in cases if c['case_id']!=case_id and str((_mapping(conn,c['case_id']) or {}).get('record_id') or _default_id(actor,c['case_id']))==str(target_record_id)]
            if not candidates:raise AccessDenied()
            target=_ensure_case(conn,candidates[0],actor)['record_id']
        current=_ensure_case(conn,case,actor)
        record=target if mode=='join' else uuid4()
        if mode!='join':conn.execute('INSERT INTO medical_records(record_id,actor_id,subject_id) VALUES (%s,%s,%s)',(record,actor,case['subject_id']))
        decision={'reason':'已按本人确认调整就医记录归属。','mode':mode}
        result=conn.execute('''UPDATE medical_record_cases SET record_id=%s,related_record_id=%s,proposed_record_id=NULL,
            assignment_source='user',status='ready',relation=%s,decision=%s::jsonb,version=version+1,updated_at=now()
            WHERE case_id=%s RETURNING version''',(record,target if mode=='related' else None,'same_episode' if mode=='join' else 'new_episode',json.dumps(decision),case_id)).fetchone()
        conn.execute('''INSERT INTO medical_record_audit(event_id,case_id,actor_id,previous_record_id,record_id,assignment_source,decision)
            VALUES (%s,%s,%s,%s,%s,'user',%s::jsonb)''',(uuid4(),case_id,actor,current['record_id'],record,json.dumps(decision)))
        return result

def claim_job(conn):
    with conn.transaction():
        conn.execute("UPDATE medical_record_jobs SET status='failed',error_code='RECORD_WORKER_INTERRUPTED',finished_at=now() WHERE status='running' AND lease_expires_at<clock_timestamp() AND attempts>=3")
        job=conn.execute('''SELECT j.run_id FROM medical_record_jobs j JOIN analysis_runs r USING(run_id)
            JOIN cases c ON c.case_id=r.case_id
            WHERE j.status='queued' OR (j.status='running' AND j.lease_expires_at<clock_timestamp() AND j.attempts<3)
            ORDER BY c.created_at,j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1''').fetchone()
        if not job:return None
        return conn.execute('''UPDATE medical_record_jobs SET status='running',attempts=attempts+1,
            lease_token=%s,lease_expires_at=now()+interval '3 minutes' WHERE run_id=%s RETURNING *''',(uuid4(),job['run_id'])).fetchone()

def _finish_job(conn,job,status,error=None,result=None):
    result=result or {}
    conn.execute('''UPDATE medical_record_jobs SET status=%s,error_code=%s,finished_at=now(),lease_token=NULL,
        lease_expires_at=NULL,model_id=%s,prompt_version=%s,usage_metadata=%s::jsonb
        WHERE run_id=%s AND lease_token=%s AND status='running' ''',(status,error,result.get('model_id'),PROMPT_VERSION,json.dumps(result.get('usage_metadata') or {}),job['run_id'],job['lease_token']))

def _model_snapshot(case,snapshot):
    sources=snapshot['sources']
    important=[s for s in sources if re.search(r'诊断|医院|门诊|住院|入院|出院|日期|复诊|复查|随访|摔|跌|外伤',s['text'])]
    chosen=list(dict((str(s['evidence_id']),s) for s in [*important,*sources]).values())[:32]
    budget=0;result=[]
    for source in chosen:
        text=source['text'][:1200]
        if budget+len(text)>14000:break
        result.append({'evidence_id':str(source['evidence_id']),'text':text});budget+=len(text)
    return {'case_id':str(case['case_id']),'sources':result,'profile':_fallback_profile(snapshot)}

def process_job(conn,job,assess=assess_record):
    if not conn.execute("SELECT 1 FROM medical_record_jobs WHERE run_id=%s AND lease_token=%s AND status='running'",(job['run_id'],job['lease_token'])).fetchone():return
    base=conn.execute('SELECT * FROM cases WHERE case_id=(SELECT case_id FROM analysis_runs WHERE run_id=%s)',(job['run_id'],)).fetchone()
    if not base:_finish_job(conn,job,'obsolete');return
    actor,subject=base['created_by'],base['subject_id']
    try:cases=_cases(conn,actor,subject)
    except AccessDenied:_finish_job(conn,job,'obsolete');return
    case=next((c for c in cases if c['case_id']==base['case_id']),None)
    snapshot=_snapshot(conn,case) if case else None
    if not snapshot or snapshot['run']['run_id']!=job['run_id']:_finish_job(conn,job,'obsolete');return
    current=_model_snapshot(case,snapshot);candidates=[];candidate_fingerprints={};ranked=[]
    current_diagnosis=(current['profile'].get('diagnosis') or {}).get('value','')
    current_text='\n'.join(s['text'] for s in current['sources'])
    for candidate in cases:
        if candidate['case_id']==case['case_id']:continue
        previous=_snapshot(conn,candidate)
        if not previous:continue
        data=_model_snapshot(candidate,previous)
        # Candidate excerpts are bounded independently of the current dossier.
        data['sources']=data['sources'][:6]
        previous_diagnosis=(data['profile'].get('diagnosis') or {}).get('value','')
        previous_text='\n'.join(s['text'] for s in data['sources'])
        score=(8 if _identifiers(current_text)&_identifiers(previous_text) else 0)+(4 if _dates(current_text)&_dates(previous_text) else 0)
        if current_diagnosis and previous_diagnosis and (current_diagnosis in previous_diagnosis or previous_diagnosis in current_diagnosis):score+=3
        ranked.append((score,data,previous['run']['run_id']))
    for _,data,run_id in sorted(ranked,key=lambda item:item[0],reverse=True):
        candidates.append(data);candidate_fingerprints[data['case_id']]=run_id
        if len(candidates)>=12:break
    result=assess(current,candidates)
    with conn.transaction():
        _lock(conn,actor,subject)
        if not conn.execute('SELECT 1 FROM medical_record_jobs WHERE run_id=%s AND lease_token=%s AND status=\'running\' FOR UPDATE',(job['run_id'],job['lease_token'])).fetchone():return
        live_cases=_cases(conn,actor,subject);live_case=next((c for c in live_cases if c['case_id']==case['case_id']),None)
        fresh=_snapshot(conn,live_case) if live_case else None
        if not fresh or fresh['run']['run_id']!=job['run_id']:_finish_job(conn,job,'obsolete');return
        current_mapping=_ensure_case(conn,case,actor)
        target_id=result.get('target_case_id') or result.get('related_case_id');target=None
        if target_id:
            previous_case=next((c for c in live_cases if str(c['case_id'])==target_id),None)
            previous=_snapshot(conn,previous_case) if previous_case else None
            if previous and previous['run']['run_id']==candidate_fingerprints.get(target_id):target=_ensure_case(conn,previous_case,actor)['record_id']
            else:result.update(automatic=False,target_case_id=None,related_case_id=None,relation='uncertain',reason='相关记录已更新，请重新核对归属。')
        record=current_mapping['record_id'];related=current_mapping['related_record_id'];proposal=None
        manual=current_mapping['assignment_source']=='user'
        # Explicit choices and established episodes survive subsequent report versions.
        established=current_mapping['assignment_source']=='ai' and current_mapping['status']=='ready'
        status='ready';assignment=current_mapping['assignment_source'];relation=current_mapping['relation']
        if not manual and not established:
            assignment='ai';relation=result.get('relation','uncertain')
            if result.get('status')!='completed':status='unavailable'
            elif result.get('automatic') and target:
                members=conn.execute('SELECT case_id,assignment_source FROM medical_record_cases WHERE record_id=%s AND case_id=ANY(%s::uuid[])',
                    (record,[c['case_id'] for c in live_cases])).fetchall()
                if target!=record and any(m['assignment_source']=='user' and m['case_id']!=case['case_id'] for m in members):
                    status='needs_confirmation';proposal=target;relation='uncertain'
                    result.update(automatic=False,reason='这份记录中已有本人确认的资料归属，请确认后再归并。')
                else:
                    if target!=record:
                        moved=conn.execute('''UPDATE medical_record_cases SET record_id=%s,version=version+1,updated_at=now()
                            WHERE record_id=%s AND case_id<>%s AND case_id=ANY(%s::uuid[]) RETURNING case_id''',
                            (target,record,case['case_id'],[c['case_id'] for c in live_cases])).fetchall()
                        for item in moved:
                            conn.execute('''INSERT INTO medical_record_audit(event_id,case_id,actor_id,run_id,previous_record_id,record_id,assignment_source,decision)
                                VALUES (%s,%s,%s,%s,%s,%s,'ai',%s::jsonb)''',(uuid4(),item['case_id'],actor,job['run_id'],record,target,
                                    json.dumps({'via_case_id':str(case['case_id']),'reason':'随其已核对的同次就医记录一起归并。'})))
                        conn.execute('UPDATE medical_record_cases SET related_record_id=%s WHERE related_record_id=%s AND case_id=ANY(%s::uuid[])',
                            (target,record,[c['case_id'] for c in live_cases]))
                        conn.execute('UPDATE medical_record_cases SET proposed_record_id=%s WHERE proposed_record_id=%s AND case_id=ANY(%s::uuid[])',
                            (target,record,[c['case_id'] for c in live_cases]))
                    record=target;related=None
            elif relation=='new_episode':related=target if result.get('related_case_id') else None
            elif relation in ('uncertain','mixed'):status='needs_confirmation';proposal=target if target!=record else None
        elif not manual and result.get('relation')=='mixed':status='needs_confirmation';relation='mixed'
        saved={k:v for k,v in result.items() if k not in {'usage_metadata','model_id'}}
        conn.execute('''UPDATE medical_record_cases SET record_id=%s,related_record_id=%s,proposed_record_id=%s,
            relation=%s,assignment_source=%s,status=%s,profile=%s::jsonb,decision=%s::jsonb,run_id=%s,
            version=version+1,updated_at=now() WHERE case_id=%s''',(record,related,proposal,relation,assignment,status,
                json.dumps(result.get('profile') or {},ensure_ascii=False),json.dumps(saved,ensure_ascii=False),job['run_id'],case['case_id']))
        conn.execute('''INSERT INTO medical_record_audit(event_id,case_id,actor_id,run_id,previous_record_id,record_id,assignment_source,decision)
            VALUES (%s,%s,%s,%s,%s,%s,'ai',%s::jsonb)''',(uuid4(),case['case_id'],actor,job['run_id'],current_mapping['record_id'],record,json.dumps(saved,ensure_ascii=False)))
        _finish_job(conn,job,'completed' if result.get('status')=='completed' else 'failed',result.get('error_code'),result)

def worker_loop(dsn,stopping):
    while not stopping():
        job=None
        try:
            with connect(dsn) as conn:
                conn.autocommit=True
                job=claim_job(conn)
                if job:process_job(conn,job)
        except Exception:
            # Best-effort organization has a separate failure state and no report writes.
            if job:
                try:
                    with connect(dsn) as conn:_finish_job(conn,job,'failed','RECORD_ORGANIZATION_FAILED')
                except Exception:pass
        for _ in range(3):
            if stopping():break
            time.sleep(1)
