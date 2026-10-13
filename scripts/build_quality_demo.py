"""Build explicitly synthetic KR4 product data using the production metric core."""
import argparse
from itertools import combinations
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from services.api.app.quality_profiles import QualityInput, ProfileMatchRequest
from scripts.quality_cli import evaluate

DEMO_VERSION = 'preliminary-synthetic-quality-v1'
METRICS = ['cost_level', 'self_paid_burden', 'medication_conformity',
           'treatment_conformity', 'guidance_completeness']
DISEASES = {'FX': '骨折', 'FY': '肺炎', 'GX': '冠心病'}


def demo_input():
    entities, records = [], []
    uid = lambda name: str(uuid5(NAMESPACE_URL, DEMO_VERSION + ':' + name))
    for disease in DISEASES:
        plan = disease + '-plan'
        entities.append({'entity_id': plan, 'entity_type': 'treatment_plan',
                         'display_name': DISEASES[disease] + '示例治疗路径【虚构】',
                         'plan_definition': 'demo-path', 'plan_version': 'v1'})
        for h in range(5):
            hospital, doctor = f'{disease}-H{h}', f'{disease}-D{h}'
            entities.extend([
                {'entity_id': hospital, 'entity_type': 'hospital',
                 'display_name': f'示例医疗机构{chr(65+h)}【虚构】'},
                {'entity_id': doctor, 'entity_type': 'doctor', 'hospital_id': hospital,
                 'doctor_role': '示例主管医师', 'display_name': f'示例医生{chr(65+h)}【虚构】'}])
            for i in range(8):
                source = uid(f'{hospital}:{i}:source')
                cost = 150000 + h * 30000 + i * 1000
                def audit(passed):
                    return {'passed': passed, 'decidable': 10, 'applicable': 10,
                            'rule_version': 'demo-audit-v1', 'reviewer_id': 'synthetic-reviewer',
                            'source_refs': [source]}
                records.append({
                    'encounter_id': uid(f'{hospital}:{i}'), 'subject_ref': f'synthetic:{hospital}:{i}',
                    'hospital_id': hospital, 'discharged_at': '2026-09-01',
                    'disease_group': disease, 'treatment_group': 'demo-path@v1',
                    'risk_group': 'demo-same-risk', 'payer_group': 'demo-same-payer',
                    'attributions': [{'entity_id': entity, 'entity_type': kind,
                                      'metrics': METRICS, 'source_refs': [source]}
                                     for kind, entity in [('hospital', hospital), ('doctor', doctor),
                                                          ('treatment_plan', plan)]],
                    'total_cost_minor': {'value': cost, 'source_refs': [source]},
                    'self_paid_minor': {'value': cost * (10 + h * 3) // 100, 'source_refs': [source]},
                    'medication_conformity': audit(8 + h % 3),
                    'treatment_conformity': audit(9 if h % 2 else 10),
                    'guidance_completeness': audit(6 + h),
                })
    return {'dataset_version': DEMO_VERSION, 'data_origin': 'synthetic',
            'entities': entities, 'records': records,
            'policy': {'version': 'demo-policy-v1', 'status': 'frozen',
                       'reviewed_by': 'synthetic-reviewer', 'reviewed_at': '2026-10-12',
                       'window_start': '2026-01-01', 'window_end': '2026-12-31',
                       'min_sample_size': 5, 'max_missing_rate': .2, 'readmission_window_days': 30,
                       'medication_rule_version': 'demo-audit-v1', 'treatment_rule_version': 'demo-audit-v1',
                       'guidance_rule_version': 'demo-audit-v1', 'feedback_question_version': 'demo-question-v1'}}


def build():
    data = QualityInput.model_validate(demo_input())
    requests = [ProfileMatchRequest(disease_group=disease, treatment_group='demo-path@v1',
                 risk_group='demo-same-risk', payer_group='demo-same-payer',
                 needs=[{'need_id': 'demo-need:' + metric, 'metric_name': metric} for metric in pair])
                for disease in DISEASES for pair in combinations(METRICS, 2)]
    result = evaluate(data, requests)
    for match in result['matches']:
        if match['coverage']['valid_two_reason_hospitals'] != 5:
            raise ValueError('demo must contain five valid two-reason hospital candidates per disease')
        if match['coverage']['ranked_hospitals'] != 0:
            raise ValueError('synthetic data must never become a trusted clinical ranking')
    return {**result, 'diseases': DISEASES, 'demo_version': DEMO_VERSION,
            'disclaimer': '虚构数据，仅用于初赛产品方案演示，不代表真实医院、医生品质或个人就医建议。',
            'formulas': {'cost_level': '实体同组费用中位数 / 同病种同组费用中位数',
                         'self_paid_burden': '明确同口径医疗个人承担金额合计 / 总费用合计',
                         'medication_conformity': '通过示例规则审核机会数 / 可判定适用机会数',
                         'treatment_conformity': '通过示例治疗标准机会数 / 可判定适用机会数',
                         'guidance_completeness': '记载完整的示例指导项 / 可判定适用项'},
            'synthetic_assumptions': '每病种五机构，每机构八个模拟病例。分层、金额和审核均为脚本假设；没有实际医学审核或真实机构数据。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='apps/web/src/quality-demo.json')
    parser.add_argument('--input-output', help='optional synthetic feature input for independent reproduction')
    parser.add_argument('--full-output', help='optional full metric provenance report outside the web bundle')
    args = parser.parse_args()
    result = build()
    # The patient bundle needs display fields and provenance IDs, not repeated policy metadata per metric.
    public = {**result, 'snapshot': {**result['snapshot'], 'profiles': [
        {**profile, 'metrics': [{key: metric[key] for key in
            ('metric_name', 'value', 'sample_count', 'missing_rate', 'metric_ref')}
            for metric in profile['metrics'] if metric['metric_name'] in METRICS]}
        for profile in result['snapshot']['profiles']]}}
    Path(args.output).write_text(json.dumps(public, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    if args.full_output:
        Path(args.full_output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.input_output:
        Path(args.input_output).write_text(json.dumps(demo_input(), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'origin': result['snapshot']['data_origin'],
                      'profiles': len(result['snapshot']['profiles']), 'diseases': len(DISEASES),
                      'hospital_pairs': 15, 'valid_dimensions': 5, 'trusted_ranking': False}))


if __name__ == '__main__':
    main()
