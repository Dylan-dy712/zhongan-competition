import json
import unittest
from unittest.mock import MagicMock
from uuid import UUID,uuid4
from services.api.app.chat_reply import decode_chat_reply
from services.api.app.conversation_agent import AgentReply, CareTools, run_agent
from services.api.app.inline_citations import bind_citations

class ChatReplyTests(unittest.TestCase):
    def test_known_turn_reference_is_history_and_unknown_uuid_remains_subject_to_checks(self):
        history,unknown=str(uuid4()),str(uuid4())
        wire={'paragraphs':[{'text':'合成历史回答。','source_refs':[history,unknown]}]}
        reply=decode_chat_reply(json.dumps(wire),{history})
        self.assertEqual(reply['history_refs'],[history])
        self.assertEqual(reply['evidence_refs'],[unknown])
        self.assertEqual(reply['citations'][0]['source_refs'],[unknown])
    def test_delivered_paragraph_itself_is_the_citation_anchor(self):
        ref=str(uuid4())
        wire={'paragraphs':[{'text':'1. **合成材料原文**','source_refs':[ref]},
                            {'text':'2. 这是知识的一般解释。','source_refs':['knowledge-1']}]}
        reply=AgentReply.model_validate(decode_chat_reply(json.dumps(wire)))
        self.assertEqual(reply.text,'1. **合成材料原文**\n\n2. 这是知识的一般解释。')
        bound=bind_citations(reply.text,reply.citations,{},reply.evidence_refs,reply.knowledge_refs)
        self.assertEqual(bound[0]['quote'],'1. 合成材料原文')
        self.assertEqual(reply.evidence_refs,[UUID(ref)])
        self.assertEqual(reply.knowledge_refs,['knowledge-1'])

    def test_newlines_repeated_phrases_and_invalid_optional_metadata_do_not_erase_body(self):
        wire={'paragraphs':[{'text':'重复的一句话。\n唯一的一句话。','source_refs':['knowledge-1']},
                            {'text':'重复的一句话。','source_refs':['knowledge-1']}],
              'clarification_questions':[{'field':'invented','question':'invalid'}],
              'patient_updates':[{'field':'medication','statement':123}],
              'suggested_questions':['',None,'有效追问？','有效追问？']}
        reply=AgentReply.model_validate(decode_chat_reply(json.dumps(wire)))
        self.assertEqual(reply.suggested_questions,['有效追问？'])
        self.assertEqual(reply.patient_updates,[])
        self.assertEqual(reply.clarification_questions,[])
        self.assertEqual(len(reply.citations),1)
        bind_citations(reply.text,reply.citations,{},reply.evidence_refs,reply.knowledge_refs)

    def test_legacy_bad_anchor_can_be_repaired_to_paragraphs_without_copying_quotes(self):
        model,tools=MagicMock(),MagicMock()
        model.complete.side_effect=[{'content':json.dumps({'text':'正文。','knowledge_refs':['k'],
            'citations':[{'quote':'复制了来源原文而不是正文。','source_refs':['k']}]})},
            {'content':json.dumps({'paragraphs':[{'text':'正文。','source_refs':['k']}]})}]
        reply,_=run_agent([], '一般问题',[],tools,model=model)
        self.assertEqual(reply['citations'],[{'quote':'正文。','source_refs':['k']}])
        self.assertEqual(model.complete.call_count,2)

    def test_prior_source_ids_are_not_reused_as_current_authorized_sources(self):
        model,tools=MagicMock(),MagicMock()
        model.complete.return_value={'content':json.dumps({'paragraphs':[{'text':'合成回答。','source_refs':[]}]})}
        history=[{'status':'completed','question':'旧问题','answer':{'text':'旧回答。','knowledge_refs':['old-secret-ref'],
            'citations':[{'quote':'旧回答。','source_refs':['old-secret-ref']}]}}]
        run_agent(history,'新问题',[],tools,model=model)
        self.assertNotIn('old-secret-ref',str(model.complete.call_args.args[0]))

    def test_paragraph_source_ids_still_require_real_authorization(self):
        tools=CareTools(MagicMock(),uuid4(),uuid4())
        reply=AgentReply.model_validate(decode_chat_reply(json.dumps({'paragraphs':[{'text':'一般解释。','source_refs':['fake-source']}]})))
        with self.assertRaisesRegex(ValueError,'UNKNOWN_KNOWLEDGE_REFERENCE'):
            tools.validate_reply(reply)
