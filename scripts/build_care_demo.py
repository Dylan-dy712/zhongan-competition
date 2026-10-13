"""Real model calls on four explicitly synthetic, source-anchored care scenarios.

Never mixed with expert-data KR1 scores or labeled as medical approval.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import time

from services.api.app.insight_llm import detect_semantic
from services.api.app.report_llm import draft_report, PROMPT_VERSION
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.insight_detector import LABEL_CATEGORY
from scripts.preliminary_kr1 import load, write

CASES = [
    {'id':'synthetic-fracture-caregiver', 'disease':'骨折',
     'material': '【完全虚构的初赛测试材料】出院诊断：左踝骨折术后。医生解释：骨折是骨头受损，本次做了固定治疗。'
       '治疗经过：2026-09-18住院，9月19日行切开复位内固定（ORIF），9月23日出院。'
       '住院用药明细与出院小结对后续用药安排记载不完整，未注明哪些药继续使用。'
       '医患沟通记录：患者表示看不懂ORIF，现有材料没有针对这个术语的通俗说明。'
       '检查记录：两次X线检查，未记载各次检查目的。'
       '出院医嘱：按主管医生确认的负重方案活动；复诊时间需联系主管医生确认；当前记录未给具体训练动作。'
       '同张收费单：医疗总费用12000元，明细合计11800元，差额原因未说明。个人现金支付3000元，不等同于个人自费。',
     'user': '我担心照顾不好自己，现在由家人陪同。我想知道复诊前要问清哪些事情，也不明白账单差额。'},
    {'id':'synthetic-pneumonia-work', 'disease':'肺炎',
     'material': '【完全虚构的初赛测试材料】出院诊断：肺炎。医生解释：肺炎指肺部炎症，本次诊断以这份记录为准。'
       '治疗经过：住院期间接受抗感染治疗，出院时症状较前改善。'
       '出院医嘱：遵医嘱继续治疗，休息；复诊日期未记载，不自行调整药物。'
       '医疗总费用6500元，药品费2000元，检查费1500元；其余分类未提供，不能将两项合计当总额。医保支付4000元，个人总负担2500元。',
     'user': '我急着回去上班，但怕休息不够。想先整理要向医生确认的事项，不希望你替医生决定我哪天能上班。'},
    {'id':'synthetic-coronary-followup', 'disease':'冠心病',
     'material': '【完全虚构的初赛测试材料】出院诊断：冠心病。医生解释：本次诊断涉及心脏供血相关问题。'
       '治疗经过：本次住院完成检查和治疗，未提供手术记录，不能据此认定做了手术。'
       '出院医嘱：按原处方规律用药，不能自行停药；具体复诊时间待门诊医生确认。'
       '费用材料：仅有医疗总费用9800元，医保结算单和明细清单未提供，支付构成待核对。',
     'user': '我担心出院以后忘记用药，想让家人帮忙核对原处方，并把需要带去复诊的资料列出来。'},
    {'id':'synthetic-fracture-independent', 'disease':'骨折',
     'material': '【完全虚构的初赛测试材料】诊断：右腕骨折。医生解释：右腕骨头受损。治疗经过：门诊固定治疗，未住院，未做手术。'
       '医嘱：固定装置不自行拆除；复诊时间以门诊安排为准，记录未给具体日期。'
       '医疗费用总额1200元，个人总负担1200元；没有其他分类明细。',
     'user': '我一个人生活，担心洗漱和做饭不方便。我不想收到关于住院手术的指导，请帮我整理生活安排和需要向医生问的问题。'},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--export-only', action='store_true')
    parser.add_argument('--public-output', help='export only the known synthetic fixture results')
    args = parser.parse_args()
    if not args.export_only:
        if not args.config:
            parser.error('live generation requires private model configuration')
        os.environ.update({k:str(v) for k,v in load(args.config).items() if k.startswith('LLM_')})
    output = Path(args.output_dir)
    mode = 'mock' if os.environ.get('LLM_PROVIDER') == 'mock' else 'live'
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('model drafts must remain outside the public repository')
    if args.export_only:
        results = [load(output/(case['id']+'.json')) for case in CASES]
        for case, result in zip(CASES,results):
            if result['data_origin'] != 'synthetic' or result['material'] != case['material'] or \
               result['user_input'] != case['user'] or result.get('medical_approval') is not False:
                raise ValueError('only exact known synthetic fixtures may be exported')
        if not args.public_output:
            parser.error('export-only requires public-output')
        public = [{key:r[key] for key in ('id','disease','data_origin','execution_mode','model_id',
                   'prompt_version','material','user_input','input_sha256','draft','insights',
                   'source_check_errors','status','medical_approval','publication_status')} for r in results]
        for record in public:
            record['insights'] = [{**item, 'category': LABEL_CATEGORY[item['label']],
                'severity': 'undetermined', 'judgment_status': 'candidate', 'review_status': 'pending'}
                for item in record['insights']]
        write(args.public_output,public)
        print(json.dumps({'exported_synthetic_cases':len(public),'medical_approval':False}))
        return
    def run(case):
        path = output/(case['id']+'.json')
        input_hash = hashlib.sha256(json.dumps(case,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if path.exists():
            previous = load(path)
            if previous.get('prompt_version') == PROMPT_VERSION and previous.get('status') == 'completed' and \
               previous.get('input_sha256') == input_hash and previous.get('model_id') == os.environ['LLM_MODEL_ID'] and \
               previous.get('execution_mode') == mode:
                return previous
        start = time.monotonic()
        report = draft_report(case['material'], [], {'concern':case['user']},
                              user_sources={'demo:user':case['user']})
        insights = detect_semantic(case['material'], [])
        draft = report.get('draft')
        errors = []
        if draft:
            for section in draft['sections']:
                if not section['claims']:
                    errors.append('empty_section:'+section['section_type'])
                for claim in section['claims']:
                    if claim['claim_type']=='case_fact' and (not claim.get('evidence_quote') or
                       claim['evidence_quote'] not in case['material']):
                        errors.append('unsupported_case_quote:'+section['section_type'])
            if {s['section_type'] for s in draft['sections']} != set(SECTION_TYPES):
                errors.append('section_coverage')
        else:
            errors.append('no_report')
        candidates = [c for c in insights.get('candidates', []) if c.get('evidence_quote') in case['material']]
        result = {'id':case['id'], 'disease':case['disease'], 'data_origin':'synthetic',
                  'execution_mode':mode, 'model_id':os.environ['LLM_MODEL_ID'],
                  'prompt_version':PROMPT_VERSION, 'material':case['material'], 'user_input':case['user'],
                  'input_sha256':input_hash,
                  'draft':draft, 'insights':candidates, 'source_check_errors':errors,
                  'status': 'completed' if not errors else 'needs_review', 'medical_approval':False,
                  'publication_status':'unpublished_demo_draft', 'usage':report.get('usage_metadata', {}),
                  'seconds':round(time.monotonic()-start,3)}
        write(path,result)
        print(json.dumps({'case':case['id'],'status':result['status'],'source_errors':len(errors)}),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,CASES))
    summary={'data_origin':'synthetic','execution_mode':mode, 'medical_approval':False,
             'diseases':sorted({r['disease'] for r in results}),
             'complete_cases':sum(r['status']=='completed' for r in results), 'cases':len(results),
             'pain_labels':sorted({c['label'] for r in results for c in r['insights']}),
             'personalization_pair':['synthetic-fracture-caregiver','synthetic-fracture-independent'],
             'human_temperature_score':'NOT_RUN'}
    write(output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__=='__main__':
    main()
