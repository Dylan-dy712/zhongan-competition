"""Local Chinese embeddings and versioned, exact pgvector retrieval."""
import json
import hashlib
import math
import os
from functools import lru_cache
from pathlib import Path

MODEL_ID = 'BAAI/bge-small-zh-v1.5'
MODEL_REVISION = '46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59'
MODEL_KEY = MODEL_ID + '@' + MODEL_REVISION + ':parts-v1'
DIMENSIONS = 512
CACHE_DIR = '/home/ubuntu/zhongan-data/embeddings'
MANIFEST = Path(__file__).resolve().parents[3] / 'contracts/knowledge/embedding-model.json'


@lru_cache(maxsize=1)
def embedding_model(cache_dir):
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest['revision'] != MODEL_REVISION or manifest['model_id'] != MODEL_ID:
        raise ValueError('EMBEDDING_MANIFEST_MISMATCH')
    model_path = Path(cache_dir) / MODEL_REVISION
    for name, expected in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('INVALID_EMBEDDING_FILE')
        digest = hashlib.sha256()
        with (model_path / name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError('EMBEDDING_MODEL_INTEGRITY_FAILED')
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_ID, cache_dir=cache_dir, threads=1,
                         specific_model_path=str(model_path), local_files_only=True)


def vector_literal(values):
    values = [float(v) for v in values]
    if len(values) != DIMENSIONS or not all(math.isfinite(v) for v in values):
        raise ValueError('INVALID_KNOWLEDGE_VECTOR')
    if not any(values):
        raise ValueError('ZERO_KNOWLEDGE_VECTOR')
    return json.dumps(values, separators=(',', ':'), allow_nan=False)


def embedding_parts(doc):
    # Stay below the model's 512-token limit, including titles and scope.
    # Every body character is indexed; overlap helps at segment boundaries.
    prefix = (doc['title'] + '\n' + doc['scope'])[:90] + '\n'
    body = doc['content']
    for start in range(0, max(1, len(body)), 300):
        yield prefix + body[start:start + 360]


class VectorUnavailable(RuntimeError):
    pass


class PgVectorSearch:
    def __init__(self, conn, model=None):
        self.conn = conn
        self.model = model

    def search(self, query, *, version, allowed_ids, document_count, limit=24):
        if not allowed_ids:
            return []
        # Savepoint protects the caller's patient-data transaction on DB failure.
        try:
            with self.conn.transaction():
                state = self.conn.execute('''SELECT document_count, vector_count FROM knowledge_vector_sets
                    WHERE corpus_version=%s AND model_id=%s''', (version, MODEL_KEY)).fetchone()
                if not state or state['document_count'] != document_count:
                    raise VectorUnavailable('index_not_ready')
                actual = self.conn.execute('''SELECT count(*) AS vectors, count(DISTINCT entry_id) AS documents
                    FROM knowledge_vectors WHERE corpus_version=%s AND model_id=%s''',
                    (version, MODEL_KEY)).fetchone()
                if actual['vectors'] != state['vector_count'] or actual['documents'] != document_count:
                    raise VectorUnavailable('index_incomplete')
                model = self.model or embedding_model(os.getenv('ZHONGAN_RAG_CACHE_DIR', CACHE_DIR))
                vector = vector_literal(next(iter(model.embed([query], batch_size=1))))
                rows = self.conn.execute('''SELECT entry_id, max(1-(embedding OPERATOR(public.<=>) %s::public.vector)) AS similarity
                    FROM knowledge_vectors WHERE corpus_version=%s AND model_id=%s
                      AND entry_id=ANY(%s)
                    GROUP BY entry_id HAVING max(1-(embedding OPERATOR(public.<=>) %s::public.vector)) >= 0.55
                    ORDER BY similarity DESC, entry_id LIMIT %s''',
                    (vector, version, MODEL_KEY, allowed_ids, vector, max(1, min(limit, 24)))).fetchall()
                return [(row['entry_id'], float(row['similarity'])) for row in rows]
        except VectorUnavailable:
            raise
        except Exception as exc:
            # Never include DSNs, patient text, or provider errors in tool output.
            raise VectorUnavailable('vector_unavailable') from exc
