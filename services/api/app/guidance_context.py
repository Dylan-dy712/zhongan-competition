"""Bounded, source-grounded priorities and diverse reference selection."""
import json
from .knowledge_retrieval import KnowledgeRetriever

def care_priorities(insights,material,knowledge_ids):
    if insights.get('status')!='completed':return []
    allowed=set(knowledge_ids)
    return [{key:item[key] for key in ('label','evidence_quote','rationale','suggested_action')}
            | {'knowledge_refs':[ref for ref in item.get('knowledge_refs',[]) if ref in allowed],
               'status':'candidate_requires_confirmation'}
            for item in insights.get('candidates',[])[:12]
            if item.get('evidence_quote') and item['evidence_quote'] in material]

def select_guidance_knowledge(entries,fields,material,user_context):
    documents=[{'entry_id':e.entry_id,'title':e.title or e.entry_id,'content':e.content,
        'disease_code':e.disease_code.value,'source':e.source,'scope':e.applicable_scope or '',
        'slot':e.slot,'anchoring':e.anchoring,'status':e.status.value,
        'ai_verified':e.ai_verified,'ai_verification_source':e.ai_verification_source}
        for e in entries if not e.numeric_pending_review]
    clinical=' '.join(str(item.get('raw_value','')) for item in fields.get('candidates',{}).get('candidates',[]))[:260]
    clinical=clinical or material[:260]
    groups=[({'S1'},'诊断 通俗 含义')]
    if any(term in material for term in ('手术','置换','内固定')):
        groups.append(({'S11'},'手术 置换 治疗 目的'))
    groups += [({'S2','S3','S4','S5','S7','S11'},'治疗 检查 目的'),
            ({'S5','S6','S7'},'康复 出院 医嘱'),({'S8','TY'},'费用 自费 支付'),
            ({'S10'},'担心 生活 准备'),({'S9','S7'},'复诊 就医 准备')]
    selected={}
    for slots,topic in groups:
        subset=[doc for doc in documents if doc['slot'] in slots]
        if not subset:continue
        concern=json.dumps(user_context or {},ensure_ascii=False)[:100] if slots=={'S10'} else ''
        recorded=material[:200] if topic=='治疗 检查 目的' else ''
        result=KnowledgeRetriever(subset).search((clinical+' '+recorded+' '+topic+' '+concern)[:400],limit=2)
        for item in result['results']:selected.setdefault(item['entry_id'],item)
    # Preserve source text; do not cut a sentence or clinical qualifier at 500 chars.
    return list(selected.values())[:12]
