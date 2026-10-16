"""Prepare one source-reviewed draft for the generic fixed judge sample."""
import argparse,json,os,subprocess,time,requests
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--conversation-id',required=True,type=UUID)
    parser.add_argument('--from-worker-environment',action='store_true');args=parser.parse_args()
    if args.from_worker_environment:
        pid=subprocess.check_output(['systemctl','show','zhongan-worker','-p','MainPID','--value'],text=True).strip()
        if not pid.isdigit() or pid=='0':raise RuntimeError('WORKER_NOT_RUNNING')
        values=dict(item.split('=',1) for item in Path('/proc',pid,'environ').read_bytes().decode().split('\0') if '=' in item)
        os.environ.update({key:value for key,value in values.items() if key.startswith(('LLM_','ZHONGAN_'))})
    from services.api.app.conversation_agent import CareTools,run_agent
    from services.api.app.conversation_repository import get_turns,get_patient_context
    from services.api.app.judge_narrative_cache import scope,read_prepared,write_prepared
    started=time.monotonic()
    with psycopg.connect(os.environ['ZHONGAN_DATABASE_URL'],row_factory=dict_row) as conn:
        conn.execute('SET default_transaction_read_only=on');conn.commit()
        current=conn.execute('SELECT * FROM conversations WHERE conversation_id=%s',(args.conversation_id,)).fetchone()
        if not current:raise RuntimeError('SAMPLE_CONVERSATION_MISSING')
        actor=current['actor_id'];run=conn.execute('SELECT run_id FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC LIMIT 1',(current['case_id'],)).fetchone()
        if not run or not scope(conn,actor,args.conversation_id,run['run_id']):raise RuntimeError('GENERIC_JUDGE_SAMPLE_REQUIRED')
        reused=read_prepared(conn,actor,args.conversation_id,run['run_id']) is not None
        if not reused:
            turns=get_turns(conn,actor,args.conversation_id)
            previous=next((turn for turn in reversed(turns) if turn['input_kind']=='analysis_ready'),None)
            if not previous:raise RuntimeError('SAMPLE_ANALYSIS_REQUEST_REQUIRED')
            history=[turn for turn in turns if turn['turn_id']!=previous['turn_id']]
            prepared=False
            for attempt in range(2):
                tools=CareTools(conn,actor,args.conversation_id);initial=tools.reusable_analysis()
                try:
                    reply,_=run_agent(history,previous['question'],[],tools,analysis_mode=True,initial_analysis=initial,
                                      patient_context=get_patient_context(conn,actor,args.conversation_id))
                except (ValueError,requests.RequestException):
                    continue  # A failed review cannot prepare or publish a draft.
                if reply.get('performance',{}).get('partial_delivery') is False and reply.get('guidance_delivery',{}).get('status')=='passed':
                    write_prepared(conn,actor,args.conversation_id,run['run_id'],reply,tools.knowledge_sources);prepared=True;break
            if not prepared:raise RuntimeError('SAMPLE_DRAFT_NOT_VERIFIED')
        print(json.dumps({'prepared_draft':True,'reused':reused,'seconds':round(time.monotonic()-started,3),
                          'created_cases':0,'published_reports':0}))

if __name__=='__main__':main()
