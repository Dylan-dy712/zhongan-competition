"""Validate explicit claim-to-source links. Never infer a link from a report-wide list."""
from pydantic import BaseModel, ConfigDict, Field


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
