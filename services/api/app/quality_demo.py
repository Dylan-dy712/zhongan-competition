"""Explicit synthetic showcase; never saved as a production quality snapshot."""
from uuid import NAMESPACE_URL, uuid5
from functools import lru_cache
from .quality_profiles import QualityInput, METRICS, build_profiles, match_profiles


@lru_cache(maxsize=1)
def demo_snapshot():
    entities, records = [], []
    for hospital in range(5):
        key = f'demo-hospital-{hospital+1}'
        entities.append({'entity_id':key,'entity_type':'hospital','display_name':f'合成示例机构 {hospital+1}'})
        for disease in ('FY','FX','TN'):
            for index in range(8):
                source = str(uuid5(NAMESPACE_URL,f'synthetic-quality:{key}:{disease}:{index}'))
                audit = {'passed':3+(hospital%2),'decidable':4,'applicable':4,'rule_version':'demo-review-v1',
                         'reviewer_id':'synthetic-reviewer','source_refs':[source]}
                records.append({'encounter_id':source,'subject_ref':f'{key}-{disease}-{index}',
                    'hospital_id':key,'discharged_at':'2026-06-01','disease_group':disease,
                    'treatment_group':'demo-care@v1','risk_group':'demo-low','payer_group':'demo-payer',
                    'attributions':[{'entity_id':key,'entity_type':'hospital','metrics':list(METRICS),'source_refs':[source]}],
                    'total_cost_minor':{'value':(hospital+3)*100000+index*1000,'source_refs':[source]},
                    'self_paid_minor':{'value':(hospital+3)*10000,'source_refs':[source]},
                    'medication_conformity':dict(audit),'treatment_conformity':dict(audit),'guidance_completeness':dict(audit),
                    'followup':{'complete':True,'unplanned_readmission':index==0,'planned_excluded':True,
                                'window_days':30,'observed_until':'2026-07-02','source_refs':[source]},
                    'feedback':{'value':3+(hospital%3),'question_version':'demo-feedback-v1','source_refs':[source]}})
    data=QualityInput.model_validate({'dataset_version':'frontend-showcase-v1','data_origin':'synthetic','entities':entities,'records':records,
        'policy':{'version':'synthetic-demo-policy-v1','status':'frozen','reviewed_by':'synthetic-reviewer','reviewed_at':'2026-07-03',
            'window_start':'2026-01-01','window_end':'2026-09-30','min_sample_size':3,'max_missing_rate':.3,
            'readmission_window_days':30,'medication_rule_version':'demo-review-v1','treatment_rule_version':'demo-review-v1',
            'guidance_rule_version':'demo-review-v1','feedback_question_version':'demo-feedback-v1'}})
    return build_profiles(data)


def demo_recommendations(request):
    snapshot=demo_snapshot()
    results=match_profiles(snapshot,**request.model_dump(exclude={'needs'}),needs=request.needs)
    names={p['entity_id']:p['display_name'] for p in snapshot['profiles']}
    return {'snapshot_id':snapshot['snapshot_id'],'data_origin':'synthetic','policy_status':'frozen',
            'results':[{**r,'entity_name':names[r['candidate_id']]} for r in results]}
