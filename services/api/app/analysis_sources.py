"""Compact model-only source aliases; patient citations remain real evidence UUIDs."""


def compact_schema(value):
    """Drop display metadata, retaining every validation constraint and reference."""
    if isinstance(value, list):
        return [compact_schema(item) for item in value]
    if isinstance(value, dict):
        return {key:({name:compact_schema(schema) for name,schema in item.items()}
                     if key in {'properties','$defs','definitions','patternProperties'} else compact_schema(item))
                for key,item in value.items() if key not in {'title','default'}}
    return value


def pack_sources(batches):
    pages, aliases, existing = {}, {}, {}
    for batch in batches:
        for item in batch.get('evidence', []):
            identity = str(item['evidence_id'])
            if identity in existing:
                continue
            alias = f'S{len(aliases)+1}'
            aliases[alias] = identity
            existing[identity] = alias
            key = (str(item.get('document_id', 'unknown')), item.get('page_index', 0))
            pages.setdefault(key, []).append([alias, item.get('text') or ''])
    documents = {}
    packed = []
    for (document, page), spans in pages.items():
        documents.setdefault(document, f'D{len(documents)+1}')
        packed.append({'document': documents[document], 'page': page, 'spans': spans})
    return packed, aliases
