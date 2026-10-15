import copy
import json
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from services.api.app.guidance_quality import GuidanceQuality
from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.report_llm import DraftReport, draft_report, normalize_report_wire


def metadata_variant():
    return {'sections': [{'section_type': s, 'claims': []} for s in SECTION_TYPES],
            'actions': [], 'review_notes': ['Internal model commentary'],
            'patient_analysis': {
                'text': '统筹支付是由医保统筹基金按规定支付的部分。本次票据列了统筹支付80元。核对个人承担金额时，可以对照同一次结算单的支付标签。',
                'evidence_refs': [], 'history_refs': [], 'knowledge_refs': ['TY-COST-02'],
                'citations': [{'quote': '统筹支付是由医保统筹基金按规定支付的部分。',
                              'source_refs': [], 'knowledge_refs': ['TY-COST-02']}]}}


class ReportFormatRecoveryTests(unittest.TestCase):
    def test_known_metadata_variants_preserve_text_and_explicit_knowledge_link(self):
        original = metadata_variant()
        wire, changes = normalize_report_wire(json.dumps(original), ['TY-COST-02'])
        self.assertEqual(wire['patient_analysis']['text'], original['patient_analysis']['text'])
        self.assertEqual(wire['patient_analysis']['citations'][0]['source_refs'], ['TY-COST-02'])
        self.assertNotIn('review_notes', wire)
        self.assertEqual(changes, ['review_notes_removed', 'citation_knowledge_refs_merged'])
        DraftReport.model_validate(wire)
        self.assertIn('review_notes', original)

    def test_unretrieved_knowledge_is_never_promoted_into_an_authorized_link(self):
        with self.assertRaisesRegex(ValueError, 'CITATION_SOURCE_NOT_AUTHORIZED'):
            normalize_report_wire(json.dumps(metadata_variant()), [])

    def test_report_wide_knowledge_list_does_not_create_sentence_links(self):
        original = metadata_variant()
        original['patient_analysis']['citations'][0].pop('knowledge_refs')
        wire, _ = normalize_report_wire(json.dumps(original), ['TY-COST-02'])
        self.assertEqual(wire['patient_analysis']['citations'][0]['source_refs'], [])
        with self.assertRaises(ValidationError):
            DraftReport.model_validate(wire)

    def test_unrecognized_fields_and_malformed_links_still_fail_strict_schema(self):
        for mutate in (lambda d: d.update(unrecognized='private value'),
                       lambda d: d['patient_analysis']['citations'][0].update(knowledge_refs='TY-COST-02'),
                       lambda d: d['patient_analysis']['citations'][0].update(source_refs=[1])):
            original = metadata_variant(); mutate(original)
            wire, _ = normalize_report_wire(json.dumps(original), ['TY-COST-02'])
            with self.assertRaises(ValidationError):
                DraftReport.model_validate(wire)

    def test_known_variants_reach_quality_review_without_a_paid_rewrite(self):
        raw = metadata_variant(); content = json.dumps(raw)
        payload = {'choices': [{'message': {'content': content}}], 'usage': {'total_tokens': 12}}
        quality = {k: True for k in GuidanceQuality.model_fields if k not in {'issues','explanations'}} | {'issues': [],
            'explanations':[{'theme':'cost','meaning_citation':1,'case_connection_segment':2,'help_segment':3}]}
        env = {'LLM_BASE_URL': 'https://qianfan.baidubce.com/v2',
               'LLM_API_KEY': 'synthetic', 'LLM_MODEL_ID': 'glm-5.3-flash'}
        with patch.dict(os.environ, env), patch.object(OpenAiCompatibleExtractor, '_call',
                side_effect=[(payload, content), ({'usage': {'total_tokens': 8}}, json.dumps(quality))]) as call:
            result = draft_report('费用：统筹支付80元。', [{'entry_id': 'TY-COST-02', 'slot': 'TY'}],
                None, analysis_sources=[{'document': 'D1', 'page': 0, 'spans': [['S1', '费用：统筹支付80元。']]}])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(call.call_count, 2)  # One draft, one mandatory quality review.
        self.assertIsNone(result['repaired_output'])
        self.assertEqual(result['raw_output'], payload)
        self.assertEqual(result['draft']['patient_analysis']['knowledge_refs'], ['TY-COST-02'])
        self.assertEqual(result['usage_metadata']['total_tokens'], 20)
        self.assertTrue(result['usage_metadata']['guidance_quality_reviews'][0]['accepted'])

    def test_repair_feedback_names_the_schema_error_without_copying_private_values(self):
        invalid = {'sections': [{'section_type': s, 'claims': []} for s in SECTION_TYPES],
                   'actions': [], 'unrecognized': 'private value'}
        valid = copy.deepcopy(invalid); valid.pop('unrecognized')
        with patch.dict(os.environ, {'LLM_BASE_URL': 'https://example.invalid', 'LLM_API_KEY': 'synthetic',
                                   'LLM_MODEL_ID': 'test-model'}), \
             patch.object(OpenAiCompatibleExtractor, '_call',
                          side_effect=[({}, json.dumps(invalid)), ({}, json.dumps(valid))]) as call:
            result = draft_report('synthetic', [], None)
        self.assertEqual(result['status'], 'completed')
        feedback = call.call_args.args[0][-1]['content']
        self.assertIn('extra_forbidden', feedback)
        self.assertIn('unrecognized', feedback)
        self.assertNotIn('private value', feedback)
        self.assertNotIn('private value', json.dumps(result['usage_metadata']['request_attempts']))
