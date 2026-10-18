import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.api.app.analysis_paragraphs import decode_analysis_paragraphs
from services.api.app.inline_citations import canonical_analysis_citations
from services.api.app.conversation_agent import run_agent
from services.api.app.analysis_review import AnalysisReview
from services.api.app.guidance_quality import GuidanceQuality


class AnalysisParagraphTests(unittest.TestCase):
    def test_real_paragraph_can_keep_more_than_six_ocr_fragment_links(self):
        aliases={f'S{i}':str(uuid4()) for i in range(1,10)}
        content=json.dumps({'paragraphs':[{'text':'一句完整的合成事实需要多处OCR碎片。','source_refs':list(aliases)}]})
        data=decode_analysis_paragraphs(content,aliases)
        result=canonical_analysis_citations(data,aliases,[])
        self.assertEqual(result['citations'][0]['source_refs'],list(aliases.values()))

    def test_paragraph_is_its_exact_anchor_with_authorized_material_and_knowledge(self):
        ref=str(uuid4())
        wire={'paragraphs':[{'text':'1. **合成诊断**','source_refs':[]},
            {'text':'本次合成材料中的事实，仍保留疑似限定。','source_refs':['S1']},
            {'text':'这是一般知识解释。','source_refs':['K1']}]}
        data=decode_analysis_paragraphs(json.dumps(wire),{'S1':ref})
        result=canonical_analysis_citations(data,{'S1':ref},['K1'])
        self.assertEqual(result['evidence_refs'],[ref])
        self.assertEqual(result['knowledge_refs'],['K1'])
        self.assertEqual(result['citations'][0],{'quote':wire['paragraphs'][1]['text'],'source_refs':[ref]})

    def test_unknown_sources_are_still_rejected(self):
        data=decode_analysis_paragraphs(json.dumps({'paragraphs':[{'text':'合成事实。','source_refs':['invented']}]}),{})
        with self.assertRaisesRegex(ValueError,'CITATION_SOURCE_NOT_AUTHORIZED'):
            canonical_analysis_citations(data,{},[])

    def test_repeated_sourced_paragraph_is_rejected_without_dropping_its_link(self):
        with self.assertRaisesRegex(ValueError,'CITATION_ANCHOR_NOT_UNIQUE'):
            decode_analysis_paragraphs(json.dumps({'paragraphs':[{'text':'重复的事实。','source_refs':['S1']},
                {'text':'重复的事实。','source_refs':['S1']}]}),{'S1':str(uuid4())})

    def test_full_final_body_is_generated_once_then_independently_reviewed(self):
        body='合成记录中的安排还需要核对，保留已有材料，向诊疗团队确认本次具体情况。'*20
        class Model:
            supports_inline_citations=True
            config=SimpleNamespace(base_url='https://qianfan.baidubce.com/v2')
            calls=reviews=quality=0
            def complete(self,messages,**kwargs):
                self.calls+=1
                assert '本轮最终JSON采用段落格式' in messages[0]['content']
                assert '另返回citations数组' not in messages[0]['content']
                return {'content':json.dumps({'paragraphs':[{'text':body,'source_refs':['S1']}]})}
            def review_analysis(self,pages,text,**kwargs):
                self.reviews+=1
                assert text==body
                assert kwargs['citations'][0]['quote']==body
                return AnalysisReview(accepted=True,issues=[])
            def review_guidance(self,*args):
                self.quality+=1
                return GuidanceQuality(**{k:True for k in GuidanceQuality.model_fields if k not in {'issues','explanations'}})
        model=Model();tools=MagicMock();tools.deferred_patient_analysis=True
        tools.execute.return_value={'status':'available','next_offset':None,
            'evidence':[{'evidence_id':str(uuid4()),'text':'合成记录中的安排还需要核对。'}]}
        reply,_=run_agent([],'完整解读',[],tools,model=model,analysis_mode=True)
        self.assertEqual(reply['text'],body)
        self.assertGreaterEqual(len(body),650)
        self.assertEqual((model.calls,model.reviews,model.quality),(1,1,1))
        self.assertEqual(len(reply['citations']),1)
