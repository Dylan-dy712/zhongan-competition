import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError
from services.api.app.quality_profiles import METRICS, QualityInput, ProfileMatchRequest, build_profiles, match_profiles
from scripts.quality_cli import evaluate, main


def fixture():
    source=str(uuid5(NAMESPACE_URL,'synthetic-source'))
    entities=[]
    records=[]
    for disease in ('FX','FY','GX'):
        for hospital in range(5):
            key=f'{disease}-H{hospital}'
            entities.append({'entity_id':key,'entity_type':'hospital','display_name':key+'【合成】'})
            for index in range(4):
                audit={'passed':3,'decidable':4,'applicable':4,'rule_version':'review-v1',
                       'reviewer_id':'synthetic-reviewer','source_refs':[source]}
                records.append({'encounter_id':str(uuid5(NAMESPACE_URL,f'{key}:{index}')),
                    'subject_ref':f'{key}-S{index}','hospital_id':key,'discharged_at':'2025-01-01',
                    'disease_group':disease,'treatment_group':'conservative@v1','risk_group':'low','payer_group':'same-payer',
                    'attributions':[{'entity_id':key,'entity_type':'hospital','metrics':list(METRICS),'source_refs':[source]}],
                    'total_cost_minor':{'value':10000*(hospital+1),'source_refs':[source]},
                    'self_paid_minor':{'value':1000*(hospital+1),'source_refs':[source]},
                    'medication_conformity':dict(audit),'treatment_conformity':dict(audit),'guidance_completeness':dict(audit),
                    'followup':{'complete':True,'unplanned_readmission':False,'planned_excluded':True,
                                'window_days':30,'observed_until':'2025-02-01','source_refs':[source]},
                    'feedback':{'value':4,'question_version':'feedback-v1','source_refs':[source]}})
    return {'dataset_version':'synthetic-test-v1','data_origin':'synthetic','entities':entities,'records':records,
        'policy':{'version':'synthetic-policy-v1','status':'frozen','reviewed_by':'synthetic-reviewer','reviewed_at':'2025-03-01',
            'window_start':'2025-01-01','window_end':'2025-12-31','min_sample_size':3,'max_missing_rate':.3,
            'readmission_window_days':30,'medication_rule_version':'review-v1','treatment_rule_version':'review-v1',
            'guidance_rule_version':'review-v1','feedback_question_version':'feedback-v1'}}


def request(disease='FX'):
    return ProfileMatchRequest(disease_group=disease,treatment_group='conservative@v1',risk_group='low',payer_group='same-payer',
                              needs=[{'need_id':'explicit-cost','metric_name':'cost_level'},
                                     {'need_id':'explicit-guidance','metric_name':'guidance_completeness'}])


class QualityProfilesTests(unittest.TestCase):
    def test_three_diseases_five_hospitals_reproducible_and_not_official(self):
        data=QualityInput.model_validate(fixture())
        result=evaluate(data,[request(d) for d in ('FX','FY','GX')])
        self.assertEqual(result['snapshot'],build_profiles(data))
        self.assertEqual(len(result['snapshot']['profiles']),15)
        self.assertFalse(result['official_kr4_verified'])
        for match in result['matches']:
            self.assertEqual(match['coverage']['valid_two_reason_hospitals'],5)
            self.assertEqual(match['coverage']['ranked_hospitals'],0)
            for candidate in match['candidates']:
                self.assertEqual(len({r['reason_code'] for r in candidate['match_reasons']}),2)
        metric=result['snapshot']['profiles'][0]['metrics'][0]
        self.assertAlmostEqual(metric['value'],1/3)
        self.assertEqual(metric['reference_median_minor'],30000)
        public=json.dumps(result)
        self.assertNotIn('subject_ref',public)
        self.assertNotIn('encounter_id',public)

    def test_missing_incomplete_followup_and_unreviewed_rules_never_become_zero(self):
        raw=fixture()
        for row in raw['records']:
            row['followup']['observed_until']='2025-01-15'
            row['feedback']=None
            row['medication_conformity']['rule_version']='unapproved-v2'
        profile=build_profiles(QualityInput.model_validate(raw))['profiles'][0]
        metrics={m['metric_name']:m for m in profile['metrics']}
        for name in ('readmission_rate','patient_feedback','medication_conformity'):
            self.assertIsNone(metrics[name]['value'])
            self.assertFalse(metrics[name]['computable'])
            self.assertEqual(metrics[name]['missing_rate'],1)

    def test_partial_audit_missing_risk_and_duplicate_encounters(self):
        raw=fixture()
        for row in raw['records']:
            row['risk_group']=None
            row['medication_conformity'].update(passed=1,decidable=1)
        metrics=build_profiles(QualityInput.model_validate(raw))['profiles'][0]['metrics']
        medicine=next(m for m in metrics if m['metric_name']=='medication_conformity')
        self.assertEqual(medicine['undetermined_rate'],.75)
        self.assertFalse(medicine['comparison_allowed'])
        raw['records'].append(deepcopy(raw['records'][0]))
        with self.assertRaises(ValidationError): QualityInput.model_validate(raw)

    def test_weighted_self_paid_and_latest_feedback_per_person(self):
        raw=fixture()
        rows=raw['records'][:4]
        for row in rows:
            row['subject_ref']='same-person'
        rows[0]['total_cost_minor']['value']=20000
        rows[0]['self_paid_minor']['value']=5000
        metrics=build_profiles(QualityInput.model_validate(raw))['profiles'][0]['metrics']
        burden=next(m for m in metrics if m['metric_name']=='self_paid_burden')
        feedback=next(m for m in metrics if m['metric_name']=='patient_feedback')
        self.assertAlmostEqual(burden['value'],8000/50000)
        self.assertEqual(feedback['sample_count'],1)
        self.assertFalse(feedback['comparison_allowed'])

    def test_doctor_and_plan_do_not_inherit_hospital_dimensions(self):
        raw=fixture()
        raw['entities']+= [{'entity_type':'doctor','entity_id':'FX-H0:D1','display_name':'合成医生',
                           'hospital_id':'FX-H0','doctor_role':'documented-attending'},
                          {'entity_type':'treatment_plan','entity_id':'plan-v1','display_name':'合成方案',
                           'plan_definition':'conservative','plan_version':'v1'}]
        for row in raw['records'][:4]:
            for kind,key in [('doctor','FX-H0:D1'),('treatment_plan','plan-v1')]:
                row['attributions'].append({'entity_type':kind,'entity_id':key,'metrics':['medication_conformity'],
                                            'source_refs':row['total_cost_minor']['source_refs']})
        profiles=build_profiles(QualityInput.model_validate(raw))['profiles']
        for profile in profiles:
            if profile['entity_type']!='hospital':
                self.assertEqual(sum(m['computable'] for m in profile['metrics']),1)
                self.assertIsNone(profile['metrics'][0]['value'])
        raw['entities'].append({'entity_type':'doctor','entity_id':'FX-H1:D2','display_name':'另一机构合成医生',
                                'hospital_id':'FX-H1','doctor_role':'attending'})
        raw['records'][0]['attributions'][-2]['entity_id']='FX-H1:D2'
        with self.assertRaises(ValidationError): QualityInput.model_validate(raw)

    def test_excluded_current_encounter_draft_policy_and_sensitive_order(self):
        raw=fixture()
        raw['excluded_encounters']=[row['encounter_id'] for row in raw['records'][:4]]
        snapshot=build_profiles(QualityInput.model_validate(raw))
        self.assertEqual(len(snapshot['profiles']),14)
        self.assertEqual(snapshot['excluded_records'],4)
        raw['policy']['status']='draft'
        matches=evaluate(QualityInput.model_validate(raw),[request()])['matches'][0]['candidates']
        self.assertTrue(all(not r['eligible'] and not r['match_reasons'] for r in matches))
        raw=fixture()
        raw['data_origin']='authorized_historical' # explicitly simulated metadata, not real medical evidence
        for row in raw['records']:
            row['total_cost_minor']['value']=10000
        matches=evaluate(QualityInput.model_validate(raw),[request()])['matches'][0]['candidates']
        self.assertTrue(all(not r['ranking_allowed'] for r in matches))
        raw['records'][0]['self_paid_minor']['value']=100000
        with self.assertRaises(ValidationError): QualityInput.model_validate(raw)

    def test_rank_uses_explicit_preference_and_refuses_same_basis_twice(self):
        raw=fixture()
        raw['data_origin']='authorized_historical' # test metadata only, not a real dataset or approval
        matches=evaluate(QualityInput.model_validate(raw),[request()])['matches'][0]['candidates']
        self.assertEqual({r['candidate_id']:r['rank'] for r in matches},{f'FX-H{i}':i+1 for i in range(5)})
        need=request().needs[0]
        with self.assertRaises(ValueError):
            match_profiles(build_profiles(QualityInput.model_validate(raw)),disease_group='FX',treatment_group='conservative@v1',
                           risk_group='low',payer_group='same-payer',needs=[need,need])
        for row in raw['records']: row['risk_group']='unknown'
        self.assertTrue(all(not r['eligible'] for r in evaluate(QualityInput.model_validate(raw),[request()])['matches'][0]['candidates']))

    def test_cli_writes_snapshot_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'input.json').write_text(json.dumps(fixture()),encoding='utf-8')
            (root/'requests.json').write_text(json.dumps([request().model_dump(mode='json')]),encoding='utf-8')
            argv=['quality_cli','--input',str(root/'input.json'),'--requests',str(root/'requests.json'),'--output',str(root/'out.json')]
            with patch('sys.argv',argv): main()
            (root/'out.json').write_text('{}',encoding='utf-8')
            with patch('sys.argv',argv), self.assertRaises(SystemExit): main()

    def test_metric_references_and_candidates_distinguish_cohort_strata(self):
        raw=fixture()
        for row in deepcopy(raw['records'][:4]):
            row['risk_group']='high'
            row['encounter_id']=str(uuid5(NAMESPACE_URL,row['encounter_id']+':high'))
            row['subject_ref']+='-high'
            raw['records'].append(row)
        result=evaluate(QualityInput.model_validate(raw),[request()])
        refs=[m['metric_ref'] for p in result['snapshot']['profiles'] for m in p['metrics']]
        self.assertEqual(len(refs),len(set(refs)))
        candidates=result['matches'][0]['candidates']
        self.assertEqual(len(candidates),5)
        self.assertTrue(all(c['eligible'] for c in candidates))
