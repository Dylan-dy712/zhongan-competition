"""Build a local-only, atomic pgvector generation for the current reference corpus."""
import argparse
import os

from services.api.app.repository import connect
from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.knowledge_vectors import (
    MODEL_ID, MODEL_KEY, CACHE_DIR, embedding_model, embedding_parts, vector_literal,
)


def build(conn, retriever, model):
    parts = [(doc['entry_id'], i, text) for doc in retriever.documents
             for i, text in enumerate(embedding_parts(doc))]
    vectors = [vector_literal(v) for v in model.embed([p[2] for p in parts], batch_size=8)]
    if len(vectors) != len(parts):
        raise ValueError('INCOMPLETE_EMBEDDING_BATCH')
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('zhongan:knowledge-vectors',0))")
        conn.execute('''INSERT INTO knowledge_vector_sets(corpus_version,model_id,document_count,vector_count)
            VALUES (%s,%s,%s,%s) ON CONFLICT (corpus_version,model_id) DO UPDATE
            SET document_count=EXCLUDED.document_count,vector_count=EXCLUDED.vector_count,built_at=now()''',
            (retriever.version, MODEL_KEY, len(retriever.documents), len(parts)))
        conn.execute('DELETE FROM knowledge_vectors WHERE corpus_version=%s AND model_id=%s',
                     (retriever.version, MODEL_KEY))
        with conn.cursor() as cursor:
            cursor.executemany('''INSERT INTO knowledge_vectors
                (corpus_version,model_id,entry_id,part_index,embedding) VALUES (%s,%s,%s,%s,%s::vector)''',
                [(retriever.version, MODEL_KEY, ref, i, vector)
                 for (ref, i, _), vector in zip(parts, vectors, strict=True)])
    return len(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    retriever = KnowledgeRetriever()
    with connect(os.environ['ZHONGAN_DATABASE_URL']) as conn:
        state = conn.execute('''SELECT s.document_count,s.vector_count,count(v.entry_id) AS actual,
            count(DISTINCT v.entry_id) AS documents FROM knowledge_vector_sets s
            LEFT JOIN knowledge_vectors v USING(corpus_version,model_id)
            WHERE s.corpus_version=%s AND s.model_id=%s GROUP BY s.document_count,s.vector_count''',
            (retriever.version, MODEL_KEY)).fetchone()
        if not args.force and state and state['document_count'] == len(retriever.documents) and \
                state['vector_count'] == state['actual'] and state['documents'] == len(retriever.documents):
            print('KNOWLEDGE_VECTORS_CURRENT documents=' + str(state['documents']))
            return
        model = embedding_model(os.getenv('ZHONGAN_RAG_CACHE_DIR', CACHE_DIR))
        count = build(conn, retriever, model)
        print(f'KNOWLEDGE_VECTORS_READY documents={len(retriever.documents)} vectors={count} model={MODEL_ID}')


if __name__ == '__main__':
    main()
