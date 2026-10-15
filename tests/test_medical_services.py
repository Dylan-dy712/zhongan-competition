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
        self.assertFalse(pending_service_reply('医院的普通部和特需部如何区分，要看医院公开说明。'))
        self.assertFalse(pending_service_reply('你担心复查结果，我会陪你一起梳理想问医生的问题。'))

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

    def test_real_model_service_planner_validates_json_arguments(self):
        model=AgentModel.__new__(AgentModel)
        model.complete=MagicMock(return_value={'content':json.dumps({'service_request':{'routes':['benefits'],'needs':['checkup']}})})
        args=model.plan_medical_services([{'role':'user','content':'我想了解体检权益'}])
        self.assertEqual(args.needs,['checkup'])
        self.assertFalse(model.complete.call_args.kwargs['allow_tools'])
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
