"""Validate explicit claim-to-source links. Never infer a link from a report-wide list."""
from pydantic import BaseModel, ConfigDict, Field

MAX_ANALYSIS_REFERENCES = 80


class InlineCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote: str = Field(min_length=2, max_length=800)
    source_refs: list[str] = Field(min_length=1, max_length=6)


def bind_citations(text, citations, aliases, evidence_refs, knowledge_refs):
    plain = text.replace('**', '')
    allowed = {str(ref) for ref in evidence_refs} | set(knowledge_refs)
    bound = []
    for citation in citations:
        item = citation.model_dump() if hasattr(citation, 'model_dump') else citation
        quote = item['quote'].replace('**', '')
        if '\n' in quote or plain.count(quote) != 1:
            raise ValueError('CITATION_ANCHOR_NOT_UNIQUE')
        refs = list(dict.fromkeys(aliases.get(ref, ref) for ref in item['source_refs']))
        if not refs or not set(refs).issubset(allowed):
            raise ValueError('CITATION_SOURCE_NOT_AUTHORIZED')
        bound.append({'quote': quote, 'source_refs': refs})
    return bound


def canonical_analysis_citations(data, aliases, knowledge_ids):
    """Derive metadata from explicit links, checked against actual read sources."""
    evidence = set(aliases.values())
    knowledge = set(knowledge_ids)
    bound = bind_citations(data['text'],data.get('citations',[]),aliases,evidence,knowledge)
    refs = list(dict.fromkeys(ref for citation in bound for ref in citation['source_refs']))
    evidence_refs = [ref for ref in refs if ref in evidence]
    knowledge_refs = [ref for ref in refs if ref in knowledge]
    if len(evidence_refs)>MAX_ANALYSIS_REFERENCES or len(knowledge_refs)>4:
        raise ValueError('ANALYSIS_CITATION_LIMIT')
    return {**data,'citations':bound,'evidence_refs':evidence_refs,'knowledge_refs':knowledge_refs}
