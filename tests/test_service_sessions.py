import json
import unittest
from unittest.mock import MagicMock,patch

from services.api.app.medical_services import MedicalServiceArgs,catalog
from services.api.app.service_sessions import ServiceSessionArgs,manage_session,restore_session
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

    def test_doctor_cannot_become_real_appointment_or_overwrite_active_service(self):
        state=self.ready_doctor()
        duplicate=self.call(state,'start',fields=self.benefit_fields)
        self.assertEqual(duplicate['session_id'],state['session_id'])
        self.assertEqual(duplicate['mode'],'doctor')

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
