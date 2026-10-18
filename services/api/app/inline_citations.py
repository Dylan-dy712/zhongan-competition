"""Validate explicit claim-to-source links. Never infer a link from a report-wide list."""
from pydantic import BaseModel, ConfigDict, Field

MAX_ANALYSIS_REFERENCES = 80
MAX_KNOWLEDGE_REFERENCES = 8

def citation_anchor_issues(text,citations):
    plain=text.replace('**','')
    return [{'citation_index':i,'occurrences':plain.count(item['quote'].replace('**','')),
             'multiline':'\n' in item['quote']}
            for i,item in enumerate(citations)
            if '\n' in item['quote'] or plain.count(item['quote'].replace('**',''))!=1]


class InlineCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote: str = Field(min_length=2, max_length=800)
    source_refs: list[str] = Field(min_length=1, max_length=16)


def bind_citations(text, citations, aliases, evidence_refs, knowledge_refs):
    plain = text.replace('**', '')
    allowed = {str(ref) for ref in evidence_refs} | set(knowledge_refs)
    bound = []
    for citation in citations:
        item = citation.model_dump() if hasattr(citation, 'model_dump') else citation
        quote = item['quote'].replace('**', '')
        # A model may copy a clause verbatim but replace its trailing semicolon
        # with a full stop. Correct only that single punctuation character;
        # words, numbers, source links and ambiguous matches stay untouched.
        punctuation='。；;，,.!?！？'
        if '\n' not in quote and plain.count(quote)==0 and quote[-1:] in punctuation:
            stem=quote[:-1]
            if len(stem)>=8 and plain.count(stem)==1:
                end=plain.index(stem)+len(stem)
                if end<len(plain) and plain[end] in punctuation:
                    quote=stem+plain[end]
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
    if len(evidence_refs)>MAX_ANALYSIS_REFERENCES or len(knowledge_refs)>MAX_KNOWLEDGE_REFERENCES:
        raise ValueError('ANALYSIS_CITATION_LIMIT')
    return {**data,'citations':bound,'evidence_refs':evidence_refs,'knowledge_refs':knowledge_refs}
