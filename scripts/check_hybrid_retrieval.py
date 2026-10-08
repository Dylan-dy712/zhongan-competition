"""Fixed, public-language retrieval smoke cases against the local reference library."""
import json
import os
import time

from services.api.app.repository import connect
from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.knowledge_vectors import PgVectorSearch

CASES = [
    ('为什么有些钱医保不给报', None, ['COST-DOC-08-']),
    ('这笔钱怎么拿去找保险公司申请赔付', None, ['COST-DOC-09-', 'COST-DOC-10-']),
    ('摔断腿之后脚趾麻了要紧吗', 'FX', ['FX-S9-']),
    ('出了院怎么养', 'FX', ['FX-S5-', 'FX-S6-']),
    ('腰疼得腿也麻了是什么原因', 'YZ', ['YZ-S1-', 'YZ-S2-']),
    ('血糖一高就得一辈子打针吗', 'TN', ['TN-S4-', 'TN-S10-']),
    ('肺部感染回家后什么时候复查', 'FY', ['FY-S5-', 'FY-S7-']),
    ('心脏放了支架就算治好了吗', 'GX', ['GX-S1-', 'GX-S6-', 'GX-S10-']),
    ('个人自费和自付有什么区别', None, ['COST-DOC-07-', 'TY-COST-']),
    ('我在外地看病还能用老家的医保吗', None, ['COST-DOC-11-']),
    ('发票丢了还能办报销吗', None, ['COST-DOC-12-', 'COST-DOC-14-']),
    ('以后还要按时回医院看看吗', 'TN', ['TN-S7-']),
]


def main():
    lexical = KnowledgeRetriever()
    with connect(os.environ['ZHONGAN_DATABASE_URL']) as conn:
        hybrid = KnowledgeRetriever(semantic=PgVectorSearch(conn))
        counts = [0, 0]
        for query, code, prefixes in CASES:
            row = {'question': query, 'disease_code': code}
            for i, (name, r) in enumerate([('bm25', lexical), ('hybrid', hybrid)]):
                start = time.monotonic()
                result = r.search(query, disease_code=code, limit=6)
                if name == 'hybrid':
                    assert result['retrieval_method'] == 'bm25+pgvector-rrf', result.get('vector_status')
                ids = [d['entry_id'] for d in result['results']]
                relevant = any(ref.startswith(tuple(prefixes)) for ref in ids[:4])
                counts[i] += int(relevant)
                row[name] = {'relevant_at_4': relevant, 'seconds': round(time.monotonic()-start, 3),
                             'results': [{'id': d['entry_id'], 'title': d['title'],
                                          'similarity': d.get('semantic_similarity')} for d in result['results']]}
            print(json.dumps(row, ensure_ascii=False), flush=True)
        for query in ['量子力学怎么计算', '红烧肉怎么做', '明天北京会下雨吗']:
            result = hybrid.search(query)
            print(json.dumps({'unrelated_question':query,'results':[
                {'id':d['entry_id'],'title':d['title'],'similarity':d.get('semantic_similarity')}
                for d in result['results']]},ensure_ascii=False),flush=True)
            assert result['results'] == [], 'UNRELATED_QUERY_MATCHED'
        print(json.dumps({'cases':len(CASES),'bm25_relevant_at_4':counts[0],
                          'hybrid_relevant_at_4':counts[1]},ensure_ascii=False))
        assert counts[1] >= counts[0] and counts[1] >= 10, 'HYBRID_RETRIEVAL_REGRESSION'


if __name__ == '__main__': main()
