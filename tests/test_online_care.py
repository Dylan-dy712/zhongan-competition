import unittest

from services.api.app.online_care import online_scope,scope_summary,select_doctor_profile
from services.api.app.service_sessions import ServiceSessionArgs,manage_session,restore_session,SESSION_INSTRUCTION


class OnlineCareTests(unittest.TestCase):
    def start(self,department='general',condition='',age=30):
        return manage_session(ServiceSessionArgs(action='start',mode='doctor',department=department,condition_name=condition,
            clinical={'routes':['online'],'needs':['consultation'],'age_years':age}),None,[condition],condition)

    def test_catalogue_is_sourced_and_does_not_claim_live_roster(self):
        data=online_scope()
        self.assertEqual(len(data['diseases']),182)
        self.assertEqual(len({x['row'] for x in data['diseases']}),182)
        for profile in data['profiles'].values():
            self.assertTrue(profile['source_ids'])
            self.assertTrue(profile['scope_note'])
            for source in profile['source_ids']:
                self.assertTrue(data['sources'][source]['url'].startswith('https://'))
        summary=scope_summary()
        self.assertFalse(summary['live_roster_verified'])
        self.assertIn('不是互联网医院全部接诊病种',summary['disease_list_scope'])
        enums=ServiceSessionArgs.model_json_schema()['properties']['department']['anyOf'][0]['enum']
        self.assertEqual(set(enums),set(data['profiles']))
        self.assertIn('不默认消化方向',SESSION_INSTRUCTION)

    def test_distinct_problems_match_different_profiles_instead_of_gastro(self):
        for disease,expected in [('慢性胃炎','gastroenterology'),('慢性咽炎','respiratory'),('痛经','gynecology'),
                ('小儿腹泻','pediatrics'),('腰肌劳损','orthopedics'),('湿疹','dermatology'),
                ('偏头痛','neurology'),('糖尿病','endocrinology'),('龋齿','dentistry')]:
            with self.subTest(disease=disease):
                state=self.start(condition=disease)
                self.assertEqual(state['department'],expected)
                self.assertEqual(state['doctor_profile']['label'],online_scope()['profiles'][expected]['label'])
                self.assertFalse(state['doctor_profile']['live_roster_verified'])
        wrong=self.start('gastroenterology','痛经')
        self.assertEqual(wrong['department'],'gynecology')

    def test_directory_match_is_not_unlimited_clinical_or_payment_eligibility(self):
        match=select_doctor_profile('general','湿疹',['我以前确诊过湿疹'])
        self.assertEqual(match['support_level'],'triage_only')
        self.assertIn('不能证明',match['scope_note'])
        self.assertTrue(match['condition_match']['in_drug_benefit_list'])
        self.assertIn('药费直赔目录',match['condition_match']['scope'])
        chronic=select_doctor_profile('general','糖尿病',['我有糖尿病'])
        self.assertFalse(chronic['condition_match']['in_drug_benefit_list'])
        self.assertEqual(chronic['id'],'endocrinology')

    def test_directory_anxiety_and_cancer_override_generic_context(self):
        for disease in ['焦虑症','肺癌','乳腺癌']:
            state=self.start('gastroenterology',disease)
            self.assertEqual(state['phase'],'blocked')
            self.assertEqual(state['speaker'],'assistant')
        data=online_scope()
        self.assertTrue(any(x['name']=='焦虑症' for x in data['diseases']))

    def test_unsupported_specialties_use_triage_without_inventing_specialist_rosters(self):
        for key in ['dermatology','ophthalmology','ent','dentistry']:
            profile=select_doctor_profile(key,'',[])
            self.assertEqual(profile['support_level'],'triage_only')
            self.assertEqual(profile['parent_department'],'全科')
        self.assertEqual(select_doctor_profile('invented-specialty','',[])['id'],'general')
        for key in ['surgery','traditional_chinese_medicine']:
            self.assertEqual(select_doctor_profile(key,'',[])['support_level'],'other_product')

    def test_condition_name_must_be_grounded_and_no_diagnosis_from_symptom_keyword(self):
        self.assertIsNone(select_doctor_profile('general','肺癌',['我咳嗽两天']))
        state=select_doctor_profile('general','',['我咳嗽两天'])
        self.assertEqual(state['id'],'general')
        self.assertNotIn('condition_match',state)

    def test_child_age_is_collected_before_confirming_handoff(self):
        state=self.start('pediatrics','小儿腹泻',age=None)
        self.assertIn('孩子年龄',state['missing_fields'])
        older=self.start('pediatrics','小儿腹泻',age=5)
        self.assertNotIn('孩子年龄',older['missing_fields'])
        self.assertTrue(any(x['label']=='就诊人年龄' for x in older['summary']))

    def test_legacy_profile_is_enriched_on_restore(self):
        legacy={'session_id':'legacy','simulation':True,'mode':'doctor','phase':'doctor_active',
            'title':'消化内科医生咨询','department':'gastroenterology'}
        restored=restore_session([{'status':'completed','answer':{'service_session':legacy}}])
        self.assertEqual(restored['doctor_profile']['id'],'gastroenterology')
        self.assertIn('未核实',restored['doctor_profile']['scope_note'])
        self.assertNotIn('doctor_profile',legacy)

    def test_changing_direction_requires_confirmation_and_does_not_reuse_previous_doctor(self):
        from tests.test_service_sessions import ServiceSessionTests
        helper=ServiceSessionTests();helper.setUp()
        active=helper.call(helper.ready_doctor(),'confirm',question='确认接入模拟医生')
        state=manage_session(ServiceSessionArgs(action='reply',mode='doctor',department='gynecology',condition_name='痛经',
            clinical=helper.clinical),active,['痛经'],'痛经')
        self.assertEqual(state['phase'],'collecting')
        self.assertEqual(state['department'],'gynecology')
        self.assertEqual(state['speaker'],'assistant')
        self.assertIn('确认模拟接入',state['notice'])
        self.assertEqual(state['fields'],{})
        self.assertEqual(active['department'],'gastroenterology')


if __name__=='__main__':unittest.main()
