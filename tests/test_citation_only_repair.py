import copy
import json
import os
import unittest
from unittest.mock import patch
import requests
from pydantic import ValidationError
from services.api.app.citation_repair import apply_citation_repairs,citation_repair_messages
from services.api.app.inline_citations import canonical_analysis_citations
from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.report_llm import draft_report
from services.api.app.guidance_quality import GuidanceQuality
from services.api.app.model_workloads import workload_options


def analysis():
    return {'text':'这份虚构票据列出检查费80元。请保留结算单以便核对支付标签。',
            'evidence_refs':['S1'],'knowledge_refs':[],'history_refs':[],
            'citations':[{'quote':'这份虚构票据列出检查费80元。','source_refs':['S1']},
                         {'quote':'这份报告中并没有出现这句文字。','source_refs':['S2']}]}


def report():
    return {'sections':[{'section_type':s,'claims':[]} for s in SECTION_TYPES],
            'actions':[],'patient_analysis':analysis()}


class CitationOnlyRepairTests(unittest.TestCase):
    def test_removing_a_non_body_annotation_preserves_prose_links_and_other_citations(self):
        original=analysis()
        repaired,audit=apply_citation_repairs(original,json.dumps({'repairs':[{'citation_index':1,'quote':None}]}))
        self.assertEqual(repaired['text'],original['text'])
        self.assertEqual(repaired['citations'],original['citations'][:1])
        self.assertEqual(audit['removed_orphan_indexes'],[1])
        canonical=canonical_analysis_citations(repaired,{'S1':'S1','S2':'S2'},[])
        self.assertEqual(canonical['evidence_refs'],['S1'])
        self.assertEqual(len(original['citations']),2)

    def test_quote_update_keeps_its_original_source_refs(self):
        original=analysis();original['citations'][1]['quote']='保留结算单便于核对。'
        fixed,_=apply_citation_repairs(original,json.dumps({'repairs':[{
            'citation_index':1,'quote':'请保留结算单以便核对支付标签。'}]}))
        self.assertEqual(fixed['citations'][1]['source_refs'],['S2'])
        self.assertEqual(fixed['text'],original['text'])

    def test_patches_cannot_rewrite_prose_change_sources_or_touch_valid_links(self):
        for patch_data in [
            {'repairs':[{'citation_index':0,'quote':None}]},
            {'repairs':[{'citation_index':1,'quote':None,'source_refs':['forged']}]},
            {'repairs':[{'citation_index':1,'quote':None}],'text':'新生成的医学事实'},
            {'repairs':[{'citation_index':1,'quote':None},{'citation_index':1,'quote':None}]},
            {'repairs':[{'citation_index':1,'quote':'正文里不存在的句子。'}]}]:
            with self.subTest(patch=patch_data),self.assertRaises((ValueError,ValidationError)):
                apply_citation_repairs(analysis(),json.dumps(patch_data))

    def test_actual_ambiguous_or_multiline_spans_cannot_be_omitted(self):
        for text,quote in [('同一句重复。\n同一句重复。','同一句重复。'),('第一句原文。\n第二句原文。','第一句原文。\n第二句原文。')]:
            value=analysis();value['text']=text;value['citations']=[{'quote':quote,'source_refs':['S1']}]
            with self.assertRaisesRegex(ValueError,'CITATION_REPAIR_INVALID'):
                apply_citation_repairs(value,json.dumps({'repairs':[{'citation_index':0,'quote':None}]}))

    def test_repair_never_delivers_a_body_with_no_citations(self):
        value=analysis();value['citations']=value['citations'][1:]
        with self.assertRaisesRegex(ValueError,'INLINE_CITATIONS_REQUIRED'):
            apply_citation_repairs(value,json.dumps({'repairs':[{'citation_index':0,'quote':None}]}))

    def test_repair_request_contains_only_body_bad_links_and_their_real_sources(self):
        pages=[{'spans':[['S1','票据检查费80元'],['S2','待核对记录'],['S3','与错误引用无关的原文']]}]
        messages=citation_repair_messages(analysis(),pages,[])
        sent=json.loads(messages[1]['content'])
        self.assertEqual(sent['original_link_sources'],{'S2':'待核对记录'})
        self.assertEqual([x['citation_index'] for x in sent['invalid_citations']],[1])
        self.assertNotIn('sections',sent)
        bad=analysis();bad['citations'][1]['source_refs']=['forged']
        with self.assertRaisesRegex(ValueError,'CITATION_SOURCE_NOT_AUTHORIZED'):
            citation_repair_messages(bad,pages,[])

    def execute(self,responses,provider='qianfan'):
        payloads=[({'choices':[{'message':{'content':json.dumps(r)}}],'usage':{'total_tokens':10}},json.dumps(r))
                  if isinstance(r,dict) else r for r in responses]
        env={'LLM_BASE_URL':'https://qianfan.baidubce.com/v2' if provider=='qianfan' else 'https://example.invalid',
             'LLM_API_KEY':'synthetic','LLM_MODEL_ID':'glm-5.3-flash'}
        with patch.dict(os.environ,env),patch.object(OpenAiCompatibleExtractor,'_call',side_effect=payloads) as call:
            result=draft_report('虚构票据检查费80元',[],None,analysis_sources=[{'spans':[['S1','虚构票据检查费80元'],['S2','待核对记录']]}])
        return result,call

    def test_orphan_repair_is_bounded_and_quality_review_still_runs(self):
        quality={k:True for k in GuidanceQuality.model_fields if k not in {'issues','explanations'}}|{'issues':[]}
        result,call=self.execute([report(),{'repairs':[{'citation_index':1,'quote':None}]},quality])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['draft']['patient_analysis']['text'],analysis()['text'])
        self.assertEqual(call.call_count,3)
        self.assertEqual(call.call_args_list[1].kwargs,{'timeout':(10,60),'workload':'citation_repair'})
        self.assertEqual(call.call_args_list[2].kwargs['workload'],'review')
        self.assertEqual(result['usage_metadata']['total_tokens'],30)
        self.assertEqual(result['usage_metadata']['request_attempts'][1]['operation'],'citation_repair')
        self.assertIn('repairs',json.loads(result['repaired_output']['choices'][0]['message']['content']))

    def test_timeout_does_not_trigger_another_whole_report_generation(self):
        result,call=self.execute([report(),requests.ReadTimeout('private')])
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.kwargs['workload'],'citation_repair')
        self.assertEqual(result['error_code'],'REPORT_MODEL_TIMEOUT')
        self.assertNotIn('private',json.dumps(result['usage_metadata']))

    def test_quality_failure_after_repair_cannot_use_a_third_draft_call(self):
        bad={k:True for k in GuidanceQuality.model_fields if k not in {'issues','explanations'}}|{'issues':['未讲清楚'],'explanation_clear':False}
        result,call=self.execute([report(),{'repairs':[{'citation_index':1,'quote':None}]},bad])
        self.assertEqual(call.call_count,3)
        self.assertEqual(result['error_code'],'REPORT_GUIDANCE_QUALITY_REJECTED')
        self.assertEqual(sum(c.kwargs['workload'] in {'narrative','citation_repair'} for c in call.call_args_list),2)

    def test_citation_repair_has_small_output_budget_without_changing_report_budget(self):
        base='https://qianfan.baidubce.com/v2';model='glm-5.3-flash'
        self.assertEqual(workload_options(base,model,'citation_repair')['max_tokens'],2048)
        self.assertEqual(workload_options(base,model,'narrative')['max_tokens'],32768)
