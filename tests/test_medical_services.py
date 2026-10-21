import json
import unittest
from unittest.mock import MagicMock,patch

from services.api.app.medical_services import MedicalServiceArgs,recommend_services,catalog,SERVICE_INVITATION,pending_service_reply,separate_service_citations
from services.api.app.conversation_agent import CareTools,run_agent,TOOLS,AgentModel,AgentReply

class MedicalServicesTests(unittest.TestCase):
    def test_only_returned_catalog_metadata_is_separated_from_clinical_citations(self):
        services=self.recommend(routes=['benefits'],needs=['checkup'])
        identifier=services['cards'][0]['id']
        reply=AgentReply(text='体检需要核对使用条件。',knowledge_refs=[identifier,'unverified-reference'],
            citations=[{'quote':'体检需要核对使用条件。','source_refs':[identifier,'unverified-reference']}])
        clean=separate_service_citations(reply,services)
        self.assertEqual(clean.knowledge_refs,['unverified-reference'])
        self.assertEqual(clean.citations[0].source_refs,['unverified-reference'])
        self.assertEqual(services['cards'][0]['source'],self.recommend(routes=['benefits'],needs=['checkup'])['cards'][0]['source'])

    def test_pending_service_guard_only_checks_model_draft_promises(self):
        self.assertTrue(pending_service_reply('我按中高端服务参考帮你查一下权益类的体检入口。'))
        self.assertTrue(pending_service_reply('我先帮你把中高端服务参考里的体检权益入口调出来。'))
        self.assertTrue(pending_service_reply('下面卡片里有公立和私立候选机构和模拟入口，你可以先看看。'))
        self.assertTrue(pending_service_reply('我把中高端服务参考里的体检相关内容调出来给你看。'))
        self.assertTrue(pending_service_reply('我先把互联网医院的入口和参考信息调出来给你。'))
        self.assertTrue(pending_service_reply('我帮你调一下上海市肿瘤专科的线下就医参考，你可以看看有哪些方向可选。'))
        self.assertTrue(pending_service_reply('我帮你调一下中高端服务参考里的线下肿瘤就医协助，看看有哪些候选安排。'))
        self.assertFalse(pending_service_reply('医院的普通部和特需部如何区分，要看医院公开说明。'))
        self.assertFalse(pending_service_reply('你担心复查结果，我会陪你一起梳理想问医生的问题。'))
        self.assertTrue(pending_service_reply('好，这次位置够具体了，我按上海市浦东新区，结合肿瘤专科就医的需求帮你查一下。','请接着刚才的需求看看附近医疗机构'))
        self.assertTrue(pending_service_reply('好，你想用线上咨询，我结合你的情况查一下可用的入口。','我想用你们的互联网医院'))

    def test_promised_service_must_complete_a_real_tool_call_before_delivery(self):
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
        final={'text':'可以查看下方体检权益，使用时核对四选一条件。','evidence_refs':[],'history_refs':[]}
        promise={**final,'text':'我先帮你把中高端服务参考里的体检权益入口调出来。'}
        model=MagicMock();model.complete.side_effect=[{'content':json.dumps(promise)},
            {'content':None,'tool_calls':[{'id':'service-repair','type':'function','function':{
                'name':'recommend_medical_services','arguments':json.dumps({'routes':['benefits'],'needs':['checkup']})}}]},
            {'content':json.dumps(final)}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            answer,events=run_agent([],'我没有症状，想了解健康体检权益。',[],tools,model=model)
        self.assertEqual(model.complete.call_count,3)
        self.assertIn('体检',answer['medical_services']['cards'][0]['title'])
        self.assertEqual(events[0]['tool'],'recommend_medical_services')

    def test_short_lookup_promise_uses_recent_service_context(self):
        for text in ['好的，我帮你查一下。','稍等，我来找找。','我先帮您看看。']:
            self.assertTrue(pending_service_reply(text,'请推荐一些线下医疗资源'))
            self.assertFalse(pending_service_reply(text,'上次那张账单是多少？'))
        for text in ['你可以自己查一下。','我无法查询实时号源。',
                     '不用我帮你查一下，你可以直接联系医院。','请问希望在哪个城市就医？']:
            self.assertFalse(pending_service_reply(text,'请推荐一些线下医疗资源'))

    def test_contextual_offline_lookup_executes_before_delivery(self):
        for history,question,location in [
            ([], '请推荐一些上海市的线下医疗资源。', '上海市'),
            ([], '请推荐一些线下医疗资源。', ''),
            ([{'question':'帮我推荐线下医院','status':'completed','input_kind':'user',
               'answer':{'text':'你希望在哪个城市就医？'}}], '上海市', '上海市')]:
            with self.subTest(question=question):
                class PlanningModel(AgentModel):
                    def __init__(self):
                        self.usage=[]
                        self.complete=MagicMock(side_effect=[
                            {'content':json.dumps({'text':'好的，我帮你查一下。'})},
                            {'content':json.dumps({'service_request':{'routes':['offline'],
                                'needs':['consultation'],'location':location}})},
                            {'content':json.dumps({'text':'下面是同城就医参考，科室及号源请向医院核对。' if location else '你希望在哪个城市就医？'})}])
                tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
                updates=[];model=PlanningModel()
                with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
                    answer,events=run_agent(history,question,[],tools,model=model,on_event=lambda value:updates.append(list(value)))
                self.assertEqual(model.complete.call_count,3)
                self.assertEqual(events,[{'tool':'recommend_medical_services','status':'available' if location else 'needs_location'}])
                self.assertEqual(updates[-1],events)
                self.assertNotIn('帮你查一下',answer['text'])
                if location:
                    self.assertTrue(answer['medical_services']['cards'])
                    self.assertTrue(all(card['kind']=='hospital' for card in answer['medical_services']['cards']))
                else:
                    self.assertFalse(answer['medical_services']['cards'])
                    self.assertTrue(answer['medical_services']['location_prompt'])

    def test_real_model_service_planner_validates_json_arguments(self):
        model=AgentModel.__new__(AgentModel)
        model.complete=MagicMock(return_value={'content':json.dumps({'service_request':{'routes':['benefits'],'needs':['checkup']}})})
        args=model.plan_medical_services([{'role':'user','content':'我想了解体检权益'}])
        self.assertEqual(args.needs,['checkup'])
        self.assertFalse(model.complete.call_args.kwargs['allow_tools'])
        model.complete.return_value={'content':'```json\n{"service_request":{"routes":["benefits"],"needs":["checkup"]}}\n```'}
        self.assertEqual(model.plan_medical_services([]).needs,['checkup'])
        model.complete.return_value={'content':None,'tool_calls':[{'function':{'name':'recommend_medical_services',
            'arguments':'{"routes":["benefits"],"needs":["checkup"]}'}}]}
        self.assertEqual(model.plan_medical_services([]).needs,['checkup'])
        model.complete.return_value={'content':None,'tool_calls':[{'function':{'name':'search_history','arguments':'{}'}}]}
        with self.assertRaisesRegex(ValueError,'INVALID_SERVICE_PLAN_TOOL'):model.plan_medical_services([])
        model.complete.return_value={'content':json.dumps({'service_request':None})}
        self.assertIsNone(model.plan_medical_services([]))
        model.complete.return_value={'content':'{"paragraphs":[]}'}
        with self.assertRaisesRegex(ValueError,'INVALID_SERVICE_PLAN'):model.plan_medical_services([])

    def test_structured_service_repair_executes_and_persists_real_cards(self):
        class PlanningModel(AgentModel):
            def __init__(self):
                self.usage=[]
                self.complete=MagicMock(side_effect=[
                    {'content':json.dumps({'text':'我先帮你把中高端服务参考里的体检权益入口调出来。'})},
                    {'content':json.dumps({'service_request':{'routes':['benefits'],'needs':['checkup']}})},
                    {'content':json.dumps({'text':'下面是体检权益的使用条件，注意四选一。'})}])
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
        model=PlanningModel()
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            answer,events=run_agent([],'我没有症状，想了解健康体检权益。',[],tools,model=model)
        self.assertEqual(model.complete.call_count,3)
        self.assertIn('体检',answer['medical_services']['cards'][0]['title'])
        self.assertEqual(events,[{'tool':'recommend_medical_services','status':'available'}])

    def recommend(self,**kwargs):
        question=kwargs.pop('question','我在上海市浦东新区，想找复查医院。')
        values={'routes':['benefits','offline','online'],'needs':['followup'],'location':'上海市浦东新区'}
        values.update(kwargs)
        return recommend_services(MedicalServiceArgs(**values),[question])

    def test_routine_followup_combines_relevant_benefit_local_options_and_online(self):
        result=self.recommend()
        self.assertEqual(result['status'],'available')
        self.assertEqual({x['kind'] for x in result['cards']},{'benefit','hospital','online'})
        self.assertEqual([x['title'] for x in result['cards'] if x['kind']=='benefit'],['门诊陪诊'])
        for x in result['cards']:
            self.assertGreaterEqual(len(x['reasons']),2)
            self.assertTrue(x['source']['url'].startswith('https://'))
            self.assertNotIn('公里',str(x))
        hospitals=[x for x in result['cards'] if x['kind']=='hospital']
        self.assertFalse(any('康复' in x['title'] or '肿瘤' in x['title'] for x in hospitals))
        self.assertTrue(all('上海' in str(x) for x in hospitals))
        self.assertTrue(any('公立' in x['tags'] for x in hospitals))
        self.assertTrue(any('私立' in x['tags'] for x in hospitals))

    def test_oncology_overrides_online_and_prioritizes_specialists(self):
        result=self.recommend(routes=['online'],needs=['consultation'],condition='oncology',visit_stage='established')
        self.assertFalse(any(x['kind']=='online' for x in result['cards']))
        hospitals=[x for x in result['cards'] if x['kind']=='hospital']
        self.assertGreaterEqual(len(hospitals),2)
        self.assertTrue(all('肿瘤' in x['title'] for x in hospitals[:2]))
        self.assertTrue(any('绿通' in x['title'] for x in result['cards'] if x['kind']=='benefit'))
        self.assertFalse(any(x['title']=='三甲图文咨询' for x in result['cards']))
        public=next(x for x in hospitals if x['title']=='复旦大学附属肿瘤医院')
        self.assertIn('历史',public['source']['title'])
        self.assertIn('重新确认',public['notice'])

    def test_legacy_oncology_specialty_also_blocks_generic_online(self):
        result=self.recommend(routes=['online'],specialty='oncology',needs=['consultation'])
        self.assertTrue(any(x['kind']=='hospital' for x in result['cards']))
        self.assertFalse(any(x['kind']=='online' for x in result['cards']))

    def test_offline_only_results_cannot_offer_unavailable_online_doctor(self):
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
        model=MagicMock();model.complete.side_effect=[
            {'content':None,'tool_calls':[{'id':'offline','type':'function','function':{
                'name':'recommend_medical_services','arguments':json.dumps({'routes':['online'],
                    'needs':['consultation'],'condition':'oncology','location':'上海市'})}}]},
            {'content':json.dumps({'text':'本次优先线下肿瘤专科。如果想先问问题，我可以帮你接入模拟医生咨询。'})},
            {'content':json.dumps({'text':'本次优先线下肿瘤专科，以下候选的资格与号源还需核实。'})}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            answer,events=run_agent([],'我确诊肿瘤，想在上海市找专科治疗。',[],tools,model=model)
        self.assertEqual(model.complete.call_count,3)
        self.assertNotIn('接入模拟医生',answer['text'])
        self.assertTrue(all(c['kind']=='hospital' for c in answer['medical_services']['cards']))
        self.assertEqual(len(events),1)

    def test_oncology_does_not_turn_unknown_location_into_online_treatment(self):
        result=self.recommend(routes=['online'],condition='oncology',location='',needs=['consultation'],question='已确诊肿瘤，想通过线上完成治疗。')
        self.assertEqual(result['status'],'needs_location')
        self.assertEqual(result['cards'],[])

    def test_lung_and_colorectal_support_keep_offline_route_and_own_eligibility(self):
        for cancer in ['lung','colorectal']:
            result=self.recommend(routes=['online'],condition='oncology',cancer_type=cancer,
                online_purpose='cancer_support',visit_stage='established',symptom_status='stable')
            online=[x for x in result['cards'] if x['kind']=='online']
            self.assertEqual([x['id'] for x in online],['online-cancer-support'])
            self.assertTrue(any(x['kind']=='hospital' for x in result['cards']))
            self.assertIn('专项',online[0]['notice'])
            self.assertIn('初筛',str(online[0]['details']))
        for cancer in ['other','unknown']:
            result=self.recommend(condition='oncology',cancer_type=cancer,online_purpose='cancer_support')
            self.assertFalse(any(x['kind']=='online' for x in result['cards']))

    def test_new_symptoms_procedure_and_first_visit_block_all_online_support(self):
        for context in [{'symptom_status':'new_or_worsening'},{'visit_stage':'first_visit'},
                        {'online_purpose':'procedure'},{'clinical_priority':'offline_assessment'}]:
            values={'condition':'oncology','cancer_type':'lung','online_purpose':'cancer_support',**context}
            result=self.recommend(**values)
            self.assertTrue(result['cards'])
            self.assertTrue(all(x['kind']=='hospital' for x in result['cards']))

    def test_followup_and_prescription_require_stable_established_common_disease(self):
        for context in [{},{'condition':'common_chronic'},
                        {'condition':'common_chronic','visit_stage':'established'}]:
            result=self.recommend(routes=['online','benefits'],needs=['consultation','medicine'],online_purpose='followup',**context)
            self.assertEqual(result['cards'],[])
            self.assertIn('明确诊断',result['clinical_prompt'])
        result=self.recommend(routes=['online'],condition='common_chronic',visit_stage='established',
            symptom_status='stable',online_purpose='followup')
        self.assertEqual([x['kind'] for x in result['cards']],['online'])
        self.assertIn('常见病',result['cards'][0]['description'])

    def test_prescription_age_limit_is_not_a_ban_on_all_child_consultation(self):
        base={'routes':['online'],'condition':'common_chronic','visit_stage':'established','symptom_status':'stable'}
        for age in [None,6,3]:
            result=self.recommend(**base,age_years=age,online_purpose='prescription',needs=['medicine'])
            self.assertFalse(any(x['kind']=='online' for x in result['cards']))
        adult=self.recommend(**base,age_years=7,online_purpose='prescription')
        self.assertEqual([x['kind'] for x in adult['cards']],['online'])
        child=self.recommend(routes=['online'],age_years=6,online_purpose='health_guidance')
        self.assertEqual([x['kind'] for x in child['cards']],['online'])

    def test_mental_and_unverified_diseases_do_not_use_generic_online_benefits(self):
        for condition in ['mental_health','other']:
            result=self.recommend(routes=['online','benefits'],needs=['consultation','medicine'],condition=condition)
            self.assertFalse(any(x['kind'] in {'online','benefit'} for x in result['cards']))
            self.assertTrue(result['notice'])
        mental=self.recommend(condition='mental_health')
        self.assertFalse(any(x['kind']=='hospital' for x in mental['cards']))
        self.assertEqual(mental['status'],'no_local_matches')

    def test_general_health_guidance_does_not_claim_diagnosis_or_prescribing(self):
        result=self.recommend(routes=['online'])
        self.assertIn('不代表可以线上确诊或开药',result['cards'][0]['description'])

    def test_oncology_respects_private_preference_and_missing_specialty(self):
        result=self.recommend(condition='oncology',institution_types=['private'])
        hospitals=[x for x in result['cards'] if x['kind']=='hospital']
        self.assertTrue(all('私立' in x['tags'] for x in hospitals))
        self.assertIn('肿瘤',hospitals[0]['title'])
        self.assertIn('不等于绿通',str(hospitals[0]['details']))
        result=self.recommend(condition='oncology',routes=['offline'],location='拉萨市',question='我在拉萨市，需要肿瘤专科')
        self.assertFalse(result['cards'])
        self.assertEqual(result['status'],'no_local_matches')

    def test_agent_passes_clinical_context_and_persists_specialist_cards(self):
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        args={'routes':['online'],'needs':['consultation'],'condition':'oncology','cancer_type':'other',
              'visit_stage':'established','symptom_status':'stable','location':'上海市'}
        model=MagicMock();model.complete.side_effect=[{'content':None,'tool_calls':[{'id':'oncology-route','type':'function',
            'function':{'name':'recommend_medical_services','arguments':json.dumps(args)}}]},
            {'content':json.dumps({'text':'这次优先肿瘤专科，绿通资格还要按保单核验。','evidence_refs':[],'history_refs':[]})}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            reply,_=run_agent([],'我乳腺癌已经确诊，目前稳定，想在上海市找合适的医生。',[],tools,model=model)
        cards=reply['medical_services']['cards']
        self.assertTrue(any(x['title']=='复旦大学附属肿瘤医院' for x in cards))
        self.assertFalse(any(x['kind']=='online' for x in cards))
        self.assertIn('肿瘤',reply['medical_services']['notice'])

    def test_missing_or_fabricated_location_never_returns_hospitals(self):
        for location in ['', '北京市']:
            result=self.recommend(location=location,question='我需要复查，想了解附近的医院。')
            self.assertEqual(result['status'],'needs_location')
            self.assertFalse(any(x['kind']=='hospital' for x in result['cards']))
            self.assertTrue(result['location_prompt'])

    def test_district_only_does_not_guess_a_city(self):
        result=self.recommend(location='朝阳区',question='想去朝阳区附近的医院')
        self.assertEqual(result['status'],'needs_location')
        self.assertFalse(any(x['kind']=='hospital' for x in result['cards']))

    def test_private_preference_and_no_cross_city_filler(self):
        result=self.recommend(institution_types=['private'])
        self.assertTrue(all('私立' in x['tags'] for x in result['cards'] if x['kind']=='hospital'))
        result=self.recommend(location='拉萨市',question='我想在拉萨市复查',routes=['offline'])
        self.assertIn(result['status'],['needs_location','no_local_matches'])
        self.assertFalse(result['cards'])

    def test_explicit_current_city_resolves_stale_district_without_guessing(self):
        current='我补充一下这次的就医信息：复查医院：这次就医就在上海市，请按上海市帮我查附近的肿瘤专科机构。'
        result=recommend_services(MedicalServiceArgs(routes=['offline'],needs=['consultation'],
            location='浦东新区',condition='oncology'),[current,'我在浦东新区'])
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['location_query'],'上海市')
        self.assertTrue(any('肿瘤' in card['title'] for card in result['cards']))
        for text in ['我不想在上海市就医','不，请按上海市以外的地区找','我想在上海市以外就医',
                     '我想在上海市或北京市就医，还没确定','之前上海市医院的报告，不表示这次就医地区']:
            result=recommend_services(MedicalServiceArgs(routes=['offline'],needs=['consultation'],location='浦东新区'),
                [text,'我在浦东新区'])
            self.assertEqual(result['status'],'needs_location')

    def test_checkup_is_exclusive_and_not_a_followup_substitute(self):
        result=self.recommend(needs=['checkup'],routes=['benefits'])
        self.assertEqual(result['cards'][0]['title'],'健康管理体检')
        self.assertIn('四类',result['cards'][0]['description'])
        result=self.recommend(needs=['checkup','followup'],routes=['benefits'])
        self.assertEqual([x['title'] for x in result['cards']],['门诊陪诊'])

    def test_urgent_never_promotes_services(self):
        result=self.recommend(clinical_priority='urgent',needs=['checkup'])
        self.assertEqual(result['status'],'urgent')
        self.assertEqual(result['cards'],[])
        self.assertIn('120',result['notice'])

    def test_green_channel_keeps_disease_and_frequency_conditions(self):
        result=self.recommend(needs=['green_channel'],routes=['benefits'])
        card=result['cards'][0]
        self.assertIn('绿通',card['title'])
        self.assertIn('初次确诊',str(card['details']))
        self.assertIn('各1次',str(card['details']))
        self.assertIn('不保证',str(card['details']))

    def test_offline_assessment_suppresses_online_and_checkup(self):
        result=self.recommend(clinical_priority='offline_assessment',needs=['checkup'])
        self.assertTrue(result['cards'])
        self.assertTrue(all(x['kind']=='hospital' for x in result['cards']))

    def test_rehabilitation_does_not_replace_missing_rehab_with_general_hospitals(self):
        result=self.recommend(needs=['rehabilitation'],routes=['offline'])
        self.assertTrue(result['cards'])
        self.assertTrue(all('康复' in str(x['details']) for x in result['cards']))

    def test_medicine_addon_and_source_coverage_are_not_assumed_verified(self):
        result=self.recommend(needs=['medicine'],routes=['benefits'])
        self.assertIn('加油包',str(result['cards'][0]['details']))
        self.assertIn('演示',result['policy_notice'])
        self.assertTrue(all(x['address'] for x in catalog()['hospitals'] if x['source_url'].endswith('1773655201526.pdf')))

    def test_tool_output_is_server_owned_persistable_and_cannot_downgrade_urgent(self):
        tools=CareTools(MagicMock(),'actor','conversation')
        tools.service_user_messages=['我想在上海市复查']
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            first=tools.execute('recommend_medical_services',json.dumps({'routes':['online'],'needs':['consultation'],'clinical_priority':'urgent'}))
            second=tools.execute('recommend_medical_services',json.dumps({'routes':['online'],'needs':['consultation']}))
        self.assertEqual(first,second)
        self.assertEqual(tools.medical_services['status'],'urgent')

    def test_agent_native_tool_loop_returns_cards_and_accepts_location_from_human_history(self):
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        model=MagicMock()
        model.complete.side_effect=[{'role':'assistant','content':None,'tool_calls':[{'id':'medical-1','type':'function','function':{'name':'recommend_medical_services','arguments':json.dumps({'routes':['offline'],'needs':['followup'],'location':'上海市浦东新区'})}}]},
            {'role':'assistant','content':json.dumps({'text':'可以，先看看你这个地区的复查候选，具体科室再确认。','evidence_refs':[],'history_refs':[]})}]
        history=[{'question':'我这次想在上海市浦东新区就医','status':'completed','input_kind':'user','answer':{'text':'知道了','medical_services':{'cards':['old']}}}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            reply,events=run_agent(history,'请帮我找找合适的医院',[],tools,model=model)
        self.assertTrue(reply['medical_services']['cards'])
        self.assertEqual(events[0]['tool'],'recommend_medical_services')
        messages=model.complete.call_args.args[0]
        self.assertNotIn('old',messages[2]['content'])
        self.assertTrue(any(x['function']['name']=='recommend_medical_services' for x in TOOLS))

    def test_report_keeps_clinical_text_and_adds_separate_nonclinical_invitation(self):
        tools=MagicMock();tools.execute.return_value={'status':'available','evidence':[],'next_offset':None}
        model=MagicMock();model.complete.return_value={'role':'assistant','content':json.dumps({'text':'目前没有可核对的材料事实。','evidence_refs':[],'history_refs':[]})}
        reply,_=run_agent([],'解读材料',[],tools,model=model,analysis_mode=True)
        self.assertEqual(reply['text'],'目前没有可核对的材料事实。')
        self.assertEqual(reply['service_guide']['text'],SERVICE_INVITATION)

if __name__=='__main__':unittest.main()
