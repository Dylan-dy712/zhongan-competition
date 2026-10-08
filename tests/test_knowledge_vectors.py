import unittest
from unittest.mock import MagicMock

from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.knowledge_vectors import PgVectorSearch, VectorUnavailable, embedding_parts, vector_literal
from tests.test_knowledge_retrieval import documents
from services.api.app.knowledge_assembler import PackExcludedError


class HybridTests(unittest.TestCase):
    def test_semantics_recall_without_shared_keywords(self):
        backend = MagicMock()
        backend.search.return_value = [('TY-COST-01', 0.82)]
        r = KnowledgeRetriever(documents(), version='v1', semantic=backend)
        result = r.search('哪些钱不在报销范围')
        self.assertEqual(result['results'][0]['entry_id'], 'TY-COST-01')
        self.assertEqual(result['retrieval_method'], 'bm25+pgvector-rrf')
        self.assertEqual(backend.search.call_args.kwargs['version'], 'v1')
        self.assertEqual(result['results'][0]['source'], '合成费用资料')

    def test_rank_fusion_rewards_agreement_and_filters_unknown_out_of_scope(self):
        backend = MagicMock()
        backend.search.return_value = [('UNKNOWN', .99), ('FX-S1-01', .95), ('FY-S1-01', .60), ('TY-COST-01', .1)]
        r = KnowledgeRetriever(documents(), semantic=backend)
        result = r.search('肺炎康复', disease_code='FY')
        self.assertEqual([d['entry_id'] for d in result['results']], ['FY-S1-01'])
        self.assertEqual(backend.search.call_args.kwargs['allowed_ids'], ['TY-COST-01', 'FY-S1-01'])

    def test_backend_failure_falls_back_without_losing_lexical_results(self):
        backend = MagicMock()
        backend.search.side_effect = VectorUnavailable('index_not_ready')
        r = KnowledgeRetriever(documents(), semantic=backend)
        result = r.search('个人自费')
        self.assertEqual(result['retrieval_method'], 'bm25')
        self.assertEqual(result['vector_status'], 'index_not_ready')
        self.assertEqual(result['results'][0]['entry_id'], 'TY-COST-01')

    def test_known_disease_context_and_exclusions_constrain_both_paths(self):
        backend, assembler = MagicMock(), MagicMock()
        backend.search.return_value = [('FX-S1-01', .9)]
        r = KnowledgeRetriever(documents(), assembler=assembler, semantic=backend)
        r.search('出了院怎么养', disease_code='FX')
        self.assertEqual(backend.search.call_args.args[0], '骨折 出了院怎么养')
        assembler.check_exclusions.side_effect = PackExcludedError('KP-FX', '合成排除')
        result = r.search('出了院怎么养', disease_code='FX', case_text='合成排除')
        self.assertNotIn('FX-S1-01', backend.search.call_args.kwargs['allowed_ids'])
        self.assertEqual(result['results'], [])

    def test_no_relevant_candidates_means_no_results(self):
        backend = MagicMock()
        backend.search.return_value = [('FX-S1-01', .2)]
        self.assertEqual(KnowledgeRetriever(documents(), semantic=backend).search('量子力学')['results'], [])

    def test_incomplete_or_stale_index_does_not_load_model(self):
        conn, model = MagicMock(), MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        with self.assertRaisesRegex(VectorUnavailable, 'index_not_ready'):
            PgVectorSearch(conn, model).search('问题', version='missing', allowed_ids=['test'], document_count=1)
        model.embed.assert_not_called()
        conn.execute.return_value.fetchone.side_effect = [dict(document_count=1, vector_count=2),
                                                         dict(documents=1, vectors=1)]
        with self.assertRaisesRegex(VectorUnavailable, 'index_incomplete'):
            PgVectorSearch(conn, model).search('问题', version='v', allowed_ids=['test'], document_count=1)
        model.embed.assert_not_called()

    def test_segments_cover_long_body_and_vectors_are_validated(self):
        parts = list(embedding_parts(dict(title='标题', scope='一般解释', content='甲'*950+'结尾重要限定')))
        self.assertTrue(any('结尾重要限定' in part for part in parts))
        self.assertTrue(all(len(part) <= 451 for part in parts))
        for values in ([1], [0]*512, [float('nan')]*512, [float('inf')]*512):
            with self.assertRaises(ValueError): vector_literal(values)
        self.assertTrue(vector_literal([1]+[0]*511).startswith('[1.0,'))


if __name__ == '__main__': unittest.main()
