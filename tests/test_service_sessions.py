import json
import unittest
from unittest.mock import MagicMock,patch

from services.api.app.medical_services import MedicalServiceArgs,catalog
from services.api.app.service_sessions import ServiceSessionArgs,manage_session,restore_session,pending_inline_service_reply,pending_session_command,grounded_field
from services.api.app.conversation_agent import CareTools,run_agent,history_answer


class ServiceSessionTests(unittest.TestCase):
    def setUp(self):
        self.clinical={'routes':['online'],'needs':['consultation']}
        self.benefit=next(x['id'] for x in catalog()['benefits'] if x['need']=='checkup')
        self.benefit_fields={'participant':'我本人','city':'上海市','preferred_time':'下周六上午'}
        self.doctor_fields={'symptoms':'胃胀','duration':'两周','current_status':'比较轻，没有加重',
            'diagnosis_history':'以前诊断过慢性胃炎','doctor_preference':'消化内科，无特别偏好'}

    def call(self,previous=None,action='start',mode='benefit',fields=None,question='',clinical=None,**kwargs):
        fields=fields or {}
        args=ServiceSessionArgs(action=action,mode=mode,service_id=self.benefit,
            fields=[{'key':k,'value':v} for k,v in fields.items()],clinical=clinical or self.clinical,**kwargs)
        return manage_session(args,previous,[question,*fields.values()],question)

    def ready_doctor(self):
        return self.call(mode='doctor',fields=self.doctor_fields,department='gastroenterology')

    def test_benefit_collect_confirm_book_and_idempotent_reconfirmation(self):
        state=self.call()
        self.assertEqual(state['phase'],'collecting')
        self.assertEqual(len(state['missing_fields']),3)
        state=self.call(state,'update',fields=self.benefit_fields)
        self.assertEqual(state['phase'],'awaiting_confirmation')
        self.assertNotIn('booking_reference',state)
        state=self.call(state,'confirm',question='确认模拟预约')
        self.assertEqual(state['phase'],'booked')
        self.assertTrue(state['booking_reference'].startswith('DEMO-'))
        self.assertIn('未占用真实',state['notice'])
        self.assertEqual(self.call(state,'confirm',question='确认模拟预约')['booking_reference'],state['booking_reference'])

    def test_consultation_benefit_uses_doctor_intake_not_appointment_fields(self):
        consultation=next(item for item in catalog()['benefits'] if item['need']=='consultation')
        args=ServiceSessionArgs(action='start',mode='benefit',service_id=consultation['id'],clinical=self.clinical)
        state=manage_session(args,None,['我想用你们的互联网医院'],'我想用你们的互联网医院')
        self.assertEqual(state['mode'],'doctor')
        self.assertEqual(state['phase'],'collecting')
        self.assertIn('主要症状或咨询问题',state['missing_fields'])
        self.assertNotIn('期望日期和时段',state['missing_fields'])
        blocked=manage_session(args.model_copy(update={'clinical':MedicalServiceArgs(**self.clinical,condition='oncology')}),None,
            ['已确诊肿瘤，想用互联网医院'],'已确诊肿瘤，想用互联网医院')
        self.assertEqual(blocked['phase'],'blocked')
        self.assertEqual(blocked['speaker'],'assistant')

    def test_unexecuted_inline_promise_requires_structured_tool_execution(self):
        args=ServiceSessionArgs(action='start',service_id=self.benefit,clinical=self.clinical,
            fields=[{'key':k,'value':v} for k,v in self.benefit_fields.items()])
        class Model:
            calls=0
            def complete(self,messages,**kwargs):
                self.calls+=1
                text=('好的，我先按你这次的需求看一下权益，然后帮你完成模拟预约。' if self.calls==1 else
                    '需求已整理，请核对使用人、城市和时间后确认模拟预约。')
                return {'content':json.dumps({'text':text,'evidence_refs':[],'history_refs':[]})}
            def plan_service_session(self,messages):return args
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        question='我本人在上海市，下周六上午想预约体检。'
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            result,events=run_agent([],question,[],tools,model=Model())
        self.assertEqual(result['service_session']['phase'],'awaiting_confirmation')
        self.assertEqual(events[0]['tool'],'manage_service_session')
        self.assertTrue(pending_inline_service_reply('我已经帮你完成模拟预约。'))
        self.assertTrue(pending_inline_service_reply('模拟预约已完成。'))
        self.assertTrue(pending_inline_service_reply('好的，我来帮你整理这次模拟接入的需求。我先按这些信息启动妇科方向的模拟咨询接入。'))
        self.assertFalse(pending_inline_service_reply('这种情况不适合在线预约，应先急诊。'))
        self.assertTrue(pending_session_command(result['service_session'],'确认模拟预约'))
        self.assertTrue(pending_session_command(result['service_session'],'结束当前模拟服务，回到暖暖继续聊。'))
        self.assertFalse(pending_session_command(result['service_session'],'不确认模拟预约'))
        self.assertTrue(pending_session_command({'phase':'doctor_active'},'日常作息有什么注意事项？'))

    def test_real_model_inline_planner_validates_json(self):
        from services.api.app.conversation_agent import AgentModel
        model=AgentModel.__new__(AgentModel)
        model.complete=MagicMock(return_value={'content':json.dumps({'session_request':{
            'action':'start','mode':'doctor','department':'gynecology','clinical':self.clinical}})})
        args=model.plan_service_session([])
        self.assertEqual(args.department,'gynecology')
        nested=ServiceSessionArgs(action='reply',clinical={**self.clinical,'condition_name':'慢性咽炎'})
        self.assertEqual(nested.condition_name,'慢性咽炎')
        self.assertNotIn('condition_name',nested.clinical.model_dump())

    def test_omitted_object_doctor_promise_starts_intake_in_chat(self):
        args=ServiceSessionArgs(action='start',mode='doctor',department='gastroenterology',clinical=self.clinical,
            fields=[{'key':key,'value':value} for key,value in self.doctor_fields.items()])
        class Model:
            calls=0
            def complete(self,messages,**kwargs):
                self.calls+=1
                return {'content':json.dumps({'text':'好的，我帮你查一下。' if self.calls==1 else '咨询需求已整理，请在当前聊天确认模拟接入。'})}
            def plan_service_session(self,messages):return args
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
        question='想找互联网医院的医生咨询：'+ '；'.join(self.doctor_fields.values())
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            answer,events=run_agent([],question,[],tools,model=Model())
        self.assertIn({'tool':'manage_service_session','status':'awaiting_confirmation'},events)
        self.assertEqual(answer['service_session']['department'],'gastroenterology')
        self.assertEqual(answer['service_session']['phase'],'awaiting_confirmation')
        self.assertFalse(pending_inline_service_reply('好的，我帮你查一下。','想找上海市的线下医院'))
        self.assertTrue(pending_inline_service_reply('好，你想用线上咨询，我结合你的情况查一下可用的入口。','我想用你们的互联网医院'))

    def test_offline_hospital_lookup_does_not_get_trapped_in_booking_planning(self):
        class Model:
            def complete(self,messages,**kwargs):return {'content':json.dumps({'text':'我帮你整理上海肿瘤专科参考，具体预约仍需确认。','evidence_refs':[],'history_refs':[]})}
            def plan_service_session(self,messages):return None
            def plan_medical_services(self,messages):return MedicalServiceArgs(routes=['offline'],needs=['consultation'],condition='oncology',location='上海市')
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            result,events=run_agent([],'我在上海市想找肿瘤专科医院。',[],tools,model=Model())
        self.assertTrue(result['medical_services']['cards'])
        self.assertTrue(all(card['kind']=='hospital' for card in result['medical_services']['cards']))

    def test_source_alignment_keeps_negation_and_only_recovers_short_conjunctions(self):
        original='和以往一样稳定、没有加重，也没有怀孕或异常出血'
        self.assertEqual(grounded_field('和以往一样稳定、没有加重，没有怀孕或异常出血',[original]),original)
        self.assertIsNone(grounded_field('有加重',['没有加重']))
        self.assertIsNone(grounded_field('稳定，已经确诊',['稳定，但是未明确诊断，已经确诊其他疾病']))
        self.assertIsNone(grounded_field('无特别偏好',['无特别医生偏好']))

    def test_cannot_confirm_missing_fields_or_invented_assent(self):
        state=self.call()
        self.assertEqual(self.call(state,'confirm',question='确认模拟预约')['phase'],'collecting')
        state=self.call(fields=self.benefit_fields)
        for question in ['不确认模拟预约','明天再决定','帮我看看是否合适']:
            self.assertEqual(self.call(state,'confirm',question=question)['phase'],'awaiting_confirmation')

    def test_modified_details_require_new_confirmation(self):
        state=self.call(fields=self.benefit_fields)
        changed=self.call(state,'confirm',fields={'preferred_time':'下周日上午'},question='确认模拟预约')
        self.assertEqual(changed['phase'],'awaiting_confirmation')
        self.assertNotIn('booking_reference',changed)
        booked=self.call(state,'confirm',question='确认模拟预约')
        modified=self.call(booked,'update',fields={'preferred_time':'下周日上午'})
        self.assertNotIn('booking_reference',modified)
        self.assertNotIn('appointment',modified)

    def test_doctor_handoff_and_followup_preserve_department(self):
        state=self.ready_doctor()
        self.assertEqual(state['phase'],'awaiting_confirmation')
        premature=self.call(state,'reply')
        self.assertNotEqual(premature.get('speaker'),'doctor_simulation')
        state=self.call(state,'confirm',question='确认接入模拟医生')
        self.assertEqual(state['phase'],'doctor_active')
        self.assertEqual(state['speaker'],'doctor_simulation')
        self.assertEqual(state['department'],'gastroenterology')
        continued=self.call(state,'reply',question='吃饭后会胀，应该注意什么？')
        self.assertEqual(continued['session_id'],state['session_id'])
        self.assertEqual(continued['speaker'],'doctor_simulation')
        self.assertIn('无真人接入',continued['notice'])

    def test_urgent_new_symptoms_oncology_cannot_bypass_routing(self):
        state=self.call(self.ready_doctor(),'confirm',question='确认接入模拟医生')
        for extra in [{'clinical_priority':'urgent'},{'clinical_priority':'offline_assessment'},
                      {'condition':'oncology'},{'symptom_status':'new_or_worsening'},
                      {'visit_stage':'first_visit'},{'condition':'mental_health'}]:
            blocked=self.call(state,'reply',clinical={**self.clinical,**extra})
            self.assertEqual(blocked['phase'],'blocked')
            self.assertEqual(blocked['speaker'],'assistant')
        urgent=self.call(state,'reply',clinical={**self.clinical,'clinical_priority':'urgent'})
        self.assertIn('120',urgent['notice'])

    def test_cancel_and_restore_do_not_resurrect_old_state(self):
        state=self.ready_doctor();ended=self.call(state,'end')
        history=[{'status':'completed','answer':{'service_session':state}},
                 {'status':'failed','answer':None},{'status':'completed','answer':{'service_session':ended}}]
        restored=restore_session(history)
        self.assertEqual(restored['phase'],'ended')
        restored['fields']['symptoms']='changed'
        self.assertNotEqual(restored['fields'],ended['fields'])
        self.assertIsNone(restore_session([]))
        self.assertEqual(self.call(ended,'confirm')['status'],'no_session')

    def test_catalog_and_grounding_required(self):
        args=ServiceSessionArgs(action='start',service_id='invented',clinical=self.clinical)
        self.assertEqual(manage_session(args,None,[],'')['status'],'invalid_service')
        args=ServiceSessionArgs(action='start',service_id=self.benefit,clinical=self.clinical,
            fields=[{'key':'city','value':'北京市'}])
        self.assertEqual(manage_session(args,None,['上海市'],'上海市')['status'],'ungrounded_field')
        args=ServiceSessionArgs(action='start',mode='doctor')
        self.assertEqual(manage_session(args,None,[],'')['status'],'needs_clinical_context')
        tools=CareTools(MagicMock(),'actor','conversation');tools.service_user_messages=['我在上海市']
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            tools.execute('manage_service_session',json.dumps({'action':'start','service_id':'invented','clinical':self.clinical}))
        self.assertFalse(tools.service_session_called)
        self.assertIsNone(tools.service_session)

    def test_doctor_cannot_become_real_appointment_or_overwrite_active_service(self):
        state=self.ready_doctor()
        duplicate=self.call(state,'start',fields=self.benefit_fields)
        self.assertEqual(duplicate['session_id'],state['session_id'])
        self.assertEqual(duplicate['mode'],'doctor')
        self.assertEqual(duplicate['status'],'active_service_conflict')

    def test_switch_pauses_checkup_and_can_restore_it_without_booking(self):
        original=self.call(fields=self.benefit_fields)
        doctor=self.call(original,'switch',mode='doctor',question='先用互联网医院咨询医生')
        self.assertEqual(doctor['mode'],'doctor')
        self.assertEqual(doctor['phase'],'collecting')
        self.assertEqual(doctor['paused_sessions'][0]['fields'],original['fields'])
        self.assertNotIn('paused_sessions',doctor['paused_sessions'][0])
        restored=self.call(doctor,'switch',question='继续之前的体检预约')
        self.assertEqual(restored['mode'],'benefit')
        self.assertEqual(restored['fields'],original['fields'])
        self.assertEqual(restored['phase'],'awaiting_confirmation')
        self.assertNotIn('booking_reference',restored)
        self.assertEqual(restored['paused_sessions'][0]['mode'],'doctor')

    def test_active_conflict_does_not_mark_an_unperformed_start_as_executed(self):
        tools=CareTools(MagicMock(),'actor','conversation');tools.service_session=self.call()
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            result=tools.execute('manage_service_session',ServiceSessionArgs(action='start',mode='doctor',clinical=self.clinical).model_dump_json())
        self.assertEqual(result['status'],'active_service_conflict')
        self.assertFalse(tools.service_session_called)
        self.assertEqual(tools.service_session['mode'],'benefit')

    def test_collecting_turns_advance_even_when_narrative_has_no_promise_phrase(self):
        class Model:
            def __init__(self,args,text):self.args=args;self.text=text
            def plan_service_session(self,messages):return self.args
            def complete(self,messages,**kwargs):return {'content':json.dumps({'text':self.text})}
        state=self.call()
        history=[{'question':'帮我约体检','status':'completed','input_kind':'user','answer':{'text':'请补充信息。','service_session':state}}]
        def advance(question,args,text):
            tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock()
            with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
                answer,events=run_agent(history,question,[],tools,model=Model(args,text))
            history.append({'question':question,'status':'completed','input_kind':'user','answer':answer})
            self.assertTrue(answer['service_session_event'])
            self.assertTrue(any(event['tool']=='manage_service_session' for event in events))
            return answer['service_session']
        ready=advance('；'.join(self.benefit_fields.values()),ServiceSessionArgs(action='update',clinical=self.clinical,
            fields=[{'key':key,'value':value} for key,value in self.benefit_fields.items()]),'信息已补充，请核对摘要。')
        self.assertEqual(ready['phase'],'awaiting_confirmation')
        doctor=advance('需要互联网医院医生',ServiceSessionArgs(action='switch',mode='doctor',clinical=self.clinical),
            '请告诉我这次的咨询问题。')
        self.assertEqual(doctor['mode'],'doctor')
        self.assertEqual(doctor['paused_sessions'][0]['mode'],'benefit')
        partial={key:value for key,value in self.doctor_fields.items() if key!='doctor_preference'}
        collecting=advance('；'.join(partial.values()),ServiceSessionArgs(action='update',mode='doctor',department='gastroenterology',
            clinical=self.clinical,fields=[{'key':key,'value':value} for key,value in partial.items()]),'还想问一下医生偏好。')
        self.assertEqual(collecting['phase'],'collecting')
        ready=advance('都可以',ServiceSessionArgs(action='update',mode='doctor',clinical=self.clinical,
            fields=[{'key':'doctor_preference','value':'都可以'}]),'需求已整理，请核对接入摘要。')
        self.assertEqual(ready['phase'],'awaiting_confirmation')
        active=advance('确认接入模拟医生',ServiceSessionArgs(action='reply',mode='doctor',clinical=self.clinical),
            '这里是对应方向的模拟医生，可以继续咨询。')
        self.assertEqual(active['phase'],'doctor_active')
        self.assertEqual(active['speaker'],'doctor_simulation')
        ended=advance('结束当前模拟服务，回到暖暖继续聊。',ServiceSessionArgs(action='end'),
            '医生咨询结束，体检需求仍保留。')
        self.assertEqual(ended['phase'],'ended')
        resumed=advance('继续之前的体检预约',ServiceSessionArgs(action='switch',mode='benefit',service_id=self.benefit,clinical=self.clinical),
            '已恢复体检需求，请核对摘要。')
        self.assertEqual(resumed['mode'],'benefit')
        self.assertEqual(resumed['phase'],'awaiting_confirmation')

    def test_agent_restores_server_state_and_labels_doctor_response(self):
        state=self.ready_doctor()
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        args={'action':'confirm','mode':'doctor','clinical':self.clinical}
        model=MagicMock();model.complete.side_effect=[{'content':None,'tool_calls':[{'id':'connect','type':'function',
            'function':{'name':'manage_service_session','arguments':json.dumps(args)}}]},
            {'content':json.dumps({'text':'这里是消化内科咨询模拟。胃胀和吃饭有什么关系？','evidence_refs':[],'history_refs':[]})}]
        history=[{'question':'胃胀两周，想找消化内科医生','status':'completed','input_kind':'user',
            'answer':{'text':'请核对接入摘要。','service_session':state}}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            result,events=run_agent(history,'确认接入模拟医生',[],tools,model=model)
        self.assertEqual(result['service_session']['phase'],'doctor_active')
        self.assertEqual(result['service_speaker'],'doctor_simulation')
        self.assertEqual(events[0]['tool'],'manage_service_session')
        self.assertEqual(history_answer(history[0]),{'text':'请核对接入摘要。'})

    def test_ordinary_reply_carries_session_without_impersonating_doctor(self):
        state=self.call(self.ready_doctor(),'confirm',question='确认接入模拟医生')
        tools=CareTools(MagicMock(),'actor','conversation');tools.validate_reply=MagicMock();tools.validate_runtime=MagicMock()
        model=MagicMock();model.complete.return_value={'content':json.dumps({'text':'我是暖暖，可以帮你解释这个词。','evidence_refs':[],'history_refs':[]})}
        history=[{'question':'确认接入模拟医生','status':'completed','answer':{'text':'模拟接入。','service_session':state}}]
        result,_=run_agent(history,'暖暖，帮我解释一个词',[],tools,model=model)
        self.assertEqual(result['service_session']['phase'],'doctor_active')
        self.assertEqual(result['service_speaker'],'assistant')

    def test_recommendation_urgent_interrupts_active_doctor_and_cannot_downgrade(self):
        tools=CareTools(MagicMock(),'actor','conversation')
        tools.service_session=self.call(self.ready_doctor(),'confirm',question='确认接入模拟医生')
        tools.service_speaker='doctor_simulation'
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':'case'}):
            tools.execute('recommend_medical_services',json.dumps({**self.clinical,'clinical_priority':'urgent'}))
            self.assertEqual(tools.service_session['phase'],'blocked')
            self.assertEqual(tools.service_speaker,'assistant')
            result=tools.execute('manage_service_session',json.dumps({'action':'reply','mode':'doctor','clinical':self.clinical}))
        self.assertEqual(result['phase'],'blocked')
        self.assertEqual(result['routing_status'],'urgent')
        self.assertIn('120',result['notice'])


if __name__=='__main__':unittest.main()
