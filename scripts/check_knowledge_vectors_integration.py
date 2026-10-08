"""Real pgvector integration with synthetic vectors, no model download or patient data."""
import os
from pathlib import Path
from uuid import uuid4

from services.api.app.repository import connect
from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.knowledge_vectors import PgVectorSearch, VectorUnavailable
from scripts.build_knowledge_vectors import build


def main():
    schema = 'vector_test_' + uuid4().hex
    class SyntheticModel:
        def embed(self, texts, **kwargs):
            for text in texts:
                yield ([1., 0.] if '自费' in text or '报销' in text else [0., 1.]) + [0.] * 510
    docs = [dict(entry_id='TY-COST-01', title='个人自费', content='目录外费用。', scope='费用术语',
                 disease_code='TY', source='合成出处', source_path='test.md'),
            dict(entry_id='FY-S1-01', title='肺炎', content='肺部感染。', scope='成人肺炎',
                 disease_code='FY', source='合成出处', source_path='test.md')]
    with connect(os.environ['ZHONGAN_DATABASE_URL']) as conn:
        conn.execute('CREATE SCHEMA ' + schema)
        conn.commit()
        try:
            conn.execute('SET search_path TO ' + schema + ',public')
            conn.execute(Path('services/api/sql/021_knowledge_vectors.sql').read_text(encoding='utf-8'))
            r = KnowledgeRetriever(docs, version='synthetic-v1')
            assert build(conn, r, SyntheticModel()) == 2
            conn.commit()
            backend = PgVectorSearch(conn, SyntheticModel())
            hybrid = KnowledgeRetriever(docs, version=r.version, semantic=backend)
            result = hybrid.search('哪些钱不能报销')
            assert result['retrieval_method'] == 'bm25+pgvector-rrf'
            assert result['results'][0]['entry_id'] == 'TY-COST-01'
            assert backend.search('报销', version=r.version, allowed_ids=['FY-S1-01'], document_count=2) == []
            assert KnowledgeRetriever(docs, version='stale', semantic=backend).search('个人自费')['vector_status'] == 'index_not_ready'
            conn.execute("DELETE FROM knowledge_vectors WHERE entry_id='FY-S1-01'")
            try:
                backend.search('报销', version=r.version, allowed_ids=['TY-COST-01'], document_count=2)
            except VectorUnavailable as exc:
                assert str(exc) == 'index_incomplete'
            else:
                raise AssertionError('Incomplete index accepted')
            assert conn.execute('SELECT 1 AS ok').fetchone()['ok'] == 1
            conn.rollback()
            conn.execute('SET search_path TO ' + schema + ',public')
            conn.execute('DROP TABLE knowledge_vectors')
            fallback = hybrid.search('个人自费')
            assert fallback['retrieval_method'] == 'bm25' and fallback['vector_status'] == 'vector_unavailable'
            assert fallback['results'][0]['entry_id'] == 'TY-COST-01'
            assert conn.execute('SELECT 1 AS ok').fetchone()['ok'] == 1
            conn.rollback()
            print('KNOWLEDGE_VECTOR_INTEGRATION_OK: actual cosine SQL, version and scope filters, rank fusion, incomplete-index fallback')
        finally:
            conn.rollback()
            conn.execute('DROP SCHEMA ' + schema + ' CASCADE')
            conn.commit()


if __name__ == '__main__': main()
