"""Local hybrid RAG over the user's authorized reference library.

Approval metadata is retained: reference use does not approve patient reports.
No patient records or queries are sent to a separate embedding service.
"""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .contracts.knowledge import DiseaseCode
from .knowledge_assembler import KnowledgeAssembler, PackExcludedError, REPO_ROOT

REFERENCE_POLICY = 'user-authorized-reference-v1'
CORPUS_PATH = REPO_ROOT / 'contracts/knowledge/rag-cost-chunks.jsonl'
REPORT_PATH = REPO_ROOT / 'contracts/knowledge/rag-build-report.json'
DISEASE_NAMES = {'FX': ('骨折',), 'FY': ('肺炎',), 'GX': ('冠心病',),
                 'YZ': ('腰椎间盘', '腰突'), 'TN': ('糖尿病',), 'TY': ('医保', '费用', '发票')}
STOP = {'什么', '怎么', '怎样', '这个', '那个', '我的', '可以', '需要', '是不是',
        '一下', '哪些', '有什么', '情况', '说明', '用户', '材料', '记录', '帮我'}


def tokens(text):
    result = re.findall(r'[a-z0-9]+', text.lower())
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        for size in (2, 3):
            result.extend(run[i:i+size] for i in range(len(run)-size+1)
                          if run[i:i+size] not in STOP)
    return result


class KnowledgeRetriever:
    def __init__(self, documents=None, version='synthetic', assembler=None, semantic=None):
        self.assembler = assembler
        self.semantic = semantic
        if documents is None:
            self.assembler = assembler or KnowledgeAssembler()
            documents = [{'entry_id': e.entry_id, 'title': e.title or e.entry_id,
                          'content': e.content, 'source': e.source or '',
                          'source_path': 'docs/medical/knowledge/'+({
                              'FX':'FX-骨折/','FY':'FY-肺炎/','GX':'GX-冠心病/',
                              'YZ':'YZ-腰椎间盘突出症/','TN':'TN-糖尿病/','TY':''}[e.disease_code.value])+e.slot_file,
                          'disease_code': e.disease_code.value, 'scope': e.applicable_scope or '',
                          'anchoring': e.anchoring or '', 'status': e.status.value,
                          'numeric_pending_review': e.numeric_pending_review}
                         for e in self.assembler.all_entries]
            extra_hash = 'none'
            if CORPUS_PATH.exists():
                raw = CORPUS_PATH.read_bytes()
                report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
                extra_hash = hashlib.sha256(raw).hexdigest()
                extra = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
                if extra_hash != report['content_sha256'] or len(extra) != report['chunks_total']:
                    raise ValueError('RAG_CORPUS_INTEGRITY_FAILED')
                documents.extend(extra)
            version = self.assembler.knowledge_version + ':cost:' + extra_hash
        self.documents = tuple(documents)
        if len({d['entry_id'] for d in self.documents}) != len(self.documents):
            raise ValueError('RAG_DUPLICATE_ID')
        self.version = version
        self.counts = [Counter(tokens(d['title']+' '+d['content'])) for d in self.documents]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths)/max(1, len(self.lengths))
        self.frequency = Counter(t for c in self.counts for t in c)
        self.by_id = {d['entry_id']: d for d in self.documents}

    def search(self, query, *, limit=4, disease_code=None, case_text=''):
        query = query.strip()[:400]
        terms = set(tokens(query))
        if not terms:
            return self._result('no_results', [])
        selected = {disease_code} if disease_code else {
            code for code, names in DISEASE_NAMES.items() if any(n in query for n in names)}
        medical = selected - {'TY'}
        if medical:
            selected = medical | {'TY'}
        blocked = set()
        if self.assembler:
            for code in medical or {'FX','FY','GX','YZ','TN'}:
                try:
                    self.assembler.check_exclusions(DiseaseCode(code), case_text or query)
                except PackExcludedError:
                    blocked.add(code)
        scored = []
        allowed = []
        for i, doc in enumerate(self.documents):
            if selected and doc['disease_code'] not in selected:
                continue
            if doc['disease_code'] in blocked:
                continue
            allowed.append(doc['entry_id'])
            count = self.counts[i]
            score = 0.0
            title_terms = set(tokens(doc['title']))
            for term in terms:
                tf = count.get(term, 0)
                if not tf:
                    continue
                df = self.frequency[term]
                idf = math.log(1+(len(self.documents)-df+0.5)/(df+0.5))
                score += idf*tf*2.5/(tf+1.5*(0.25+0.75*self.lengths[i]/max(1,self.average)))
                if term in title_terms:
                    score += idf
            if score > 0:
                scored.append((score, doc['entry_id'], doc))
        scored.sort(key=lambda row: (-row[0], row[1]))
        method, degraded = 'bm25', None
        semantic_scores = {}
        if self.semantic and allowed:
            from .knowledge_vectors import VectorUnavailable
            try:
                context = '、'.join(DISEASE_NAMES[code][0] for code in sorted(medical))
                semantic_query = (context + ' ' + query).strip()
                candidates = self.semantic.search(semantic_query, version=self.version, allowed_ids=allowed,
                                                  document_count=len(self.documents), limit=24)
                semantic_scores = {ref: similarity for ref, similarity in candidates
                                   if ref in allowed and math.isfinite(similarity) and similarity >= 0.55}
                method = 'bm25+pgvector-rrf'
            except VectorUnavailable as exc:
                degraded = str(exc)
            if semantic_scores:
                # Rank fusion avoids comparing incompatible BM25 and cosine scales.
                fused = Counter()
                for rank, (_, ref, _) in enumerate(scored[:24], 1):
                    if ref in semantic_scores:
                        fused[ref] += 1 / (20 + rank)
                for rank, ref in enumerate(semantic_scores, 1):
                    fused[ref] += 1 / (20 + rank)
                scored = sorted([(score, ref, self.by_id[ref]) for ref, score in fused.items()],
                                key=lambda row: (-row[0], row[1]))
            elif method == 'bm25+pgvector-rrf':
                # A working semantic path found no sufficiently related passage.
                # Don't promote incidental n-grams for unrelated questions.
                scored = []
        hits = [{**doc, 'version': self.version, 'score': round(score, 4),
                 'use': 'general_reference', 'reference_policy': REFERENCE_POLICY}
                for score, _, doc in scored[:max(1,min(limit,6))]]
        for hit in hits:
            if hit['entry_id'] in semantic_scores:
                hit['semantic_similarity'] = round(semantic_scores[hit['entry_id']], 4)
        result = self._result('available' if hits else 'no_results', hits)
        result['retrieval_method'] = method
        if degraded:
            result['vector_status'] = degraded
        return result

    def _result(self, status, hits):
        return {'status': status, 'results': hits, 'knowledge_version': self.version,
                'retrieval_method': 'bm25', 'indexed_count': len(self.documents),
                'notice': '知识用于一般解释，不是本人的诊断、处方或保险赔付结论。'}
