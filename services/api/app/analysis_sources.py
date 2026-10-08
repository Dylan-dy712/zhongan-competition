"""Compact model-only source aliases; patient citations remain real evidence UUIDs."""


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
