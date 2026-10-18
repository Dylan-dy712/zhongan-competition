"""Automatic, source-backed history retrieval. No extracted medical fact store."""
import json
import os
import re

from .conversation_repository import AUTHORIZED, require_conversation


def enabled():
    return os.getenv('ZHONGAN_AUTOMATIC_HISTORY_ENABLED', '1') == '1'


def rows(conn, actor, conversation_id, *, turn_ids=None, locked=False, keywords=None, material_sources=False):
    from .memory_repository import require_member, lock_scope
    current = require_conversation(conn, actor, conversation_id)
    if locked:
        lock_scope(conn, actor, current['subject_id'])
        current = require_conversation(conn, actor, conversation_id, locked=True)
    require_member(conn, actor, current['subject_id'])
    # Defaults of the retired editor must not block history. An explicitly
    # withdrawn source (version > 0) remains withdrawn, including after rollout.
    query = '''SELECT t.turn_id,t.question,t.created_at,v.title,v.case_id,v.conversation_id,
        co.version AS consent_version,v.memory_settings_version AS source_version ''' + AUTHORIZED.replace(
        ' WHERE v.actor_id=%s', ''' JOIN conversation_turns t ON t.conversation_id=v.conversation_id
        JOIN consents co ON co.consent_id=c.consent_id WHERE v.actor_id=%s''') + '''
        AND c.subject_id=%s AND co.subject_id=c.subject_id AND t.status='completed' AND t.input_kind='user'
        AND t.created_at>=p.granted_at
        AND (v.memory_settings_version=0 OR v.memory_export_enabled=true)'''
    params = [actor, current['subject_id']]
    if turn_ids is None:
        query += ' AND v.conversation_id<>%s'
        params.append(conversation_id)
        if keywords:
            query += ' AND t.question ILIKE ANY(%s::text[])'
            params.append(['%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                           for word in keywords])
        if material_sources:
            query = query.replace('SELECT t.turn_id,', '''SELECT DISTINCT ON (v.case_id)
                (SELECT max(r.created_at) FROM reports r WHERE r.case_id=v.case_id) AS report_recorded_at,t.turn_id,''', 1)
            query += ' AND EXISTS(SELECT 1 FROM reports r WHERE r.case_id=v.case_id)'
            query += ' ORDER BY v.case_id,t.created_at DESC,t.turn_id DESC'
            query = 'SELECT * FROM (' + query + ') sources ORDER BY report_recorded_at DESC LIMIT 3'
        else:
            query += ' ORDER BY t.created_at DESC,t.turn_id DESC LIMIT 32'
    else:
        query += ' AND t.turn_id=ANY(%s::uuid[])'
        params.append(turn_ids)
    if locked:
        query += ' FOR SHARE OF t,v,p,co,ac,a'
    return conn.execute(query, params).fetchall()


def reference(row):
    # Zero denotes source-backed automatic history, not a synthetic consent.
    ref = {'source_turn_id': str(row['turn_id']), 'consent_version': row['consent_version'],
           'source_version': row['source_version'], 'memory_consent_version': 0, 'epoch': 0}
    if row.get('material_ref'):
        ref['material'] = row['material_ref']
    return ref


def merge_reference(old, new):
    # A later user-text lookup cannot erase a material dependency already used.
    return {**new, **({'material': old['material']} if old and old.get('material') and not new.get('material') else {})}


def material_packet(conn, actor, row, *, locked=False):
    from .material_report import get_material_report
    if locked:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f"case-report:{row['case_id']}",))
        conn.execute('SELECT case_id FROM cases WHERE case_id=%s FOR UPDATE',(row['case_id'],)).fetchone()
        conn.execute('SELECT report_id FROM reports WHERE case_id=%s FOR SHARE',(row['case_id'],)).fetchall()
    from .repository import AccessDenied
    try:
        report = get_material_report(conn, actor, row['conversation_id'])
    except AccessDenied:
        return None
    if report.get('status') != 'available':
        return None
    sections, size, evidence = [], 0, set()
    for section in report['sections']:
        if section['section_type'] not in {'diagnosis_explanation','treatment_review','next_visit_advice'}:
            continue
        items = []
        for item in section['items']:
            # Whole checked statements/source spans only, never an old assistant summary.
            if not item['evidence_refs'] or size + len(item['text']) > 2400:
                continue
            items.append(item)
            size += len(item['text'])
            evidence.update(item['evidence_refs'])
        if items:
            sections.append({'section_type':section['section_type'],'items':items})
    if not sections:
        return None
    return {'reference':{key:report[key] for key in ('report_id','run_id','source_report_version','validation_hash')},
            'sections':sections,'evidence_refs':sorted(evidence)}


def material_history(conn, actor, conversation_id):
    result = []
    for row in rows(conn, actor, conversation_id, material_sources=True):
        packet = material_packet(conn, actor, row)
        if packet:
            result.append({**row,'material_ref':packet['reference'],'material_context':packet})
        if len(result) == 2:
            break
    return result


def available(conn, actor, conversation_id, refs, *, locked=False):
    if not enabled():
        return False
    found = rows(conn, actor, conversation_id, turn_ids=[ref['source_turn_id'] for ref in refs], locked=locked)
    allowed = {(str(row['turn_id']), row['consent_version'], row['source_version']) for row in found}
    if not all((str(ref.get('source_turn_id')), ref.get('consent_version'), ref.get('source_version')) in allowed for ref in refs):
        return False
    by_turn = {str(row['turn_id']):row for row in found}
    packets = {}
    for ref in sorted(refs,key=lambda ref:str(by_turn[str(ref['source_turn_id'])]['case_id'])):
        if ref.get('material'):
            row = by_turn[str(ref['source_turn_id'])]
            key = str(row['case_id'])
            if key not in packets:
                packets[key] = material_packet(conn,actor,row,locked=locked)
            packet = packets[key]
            if not packet or packet['reference'] != ref['material']:
                return False
    return True


def retrieve(conn, actor, conversation_id, query, *, include_recent=True):
    from .memory_service import rank_documents
    import subprocess
    corpus = rows(conn, actor, conversation_id)
    # Search all authorized history for older topic matches as well as recency.
    # SQL only bounds the candidate set; Semantix performs final lexical ranking.
    words = re.findall(r'[a-zA-Z0-9]{2,}|[\u4e00-\u9fff]+', query.lower())
    keywords = list(dict.fromkeys(part for word in words for part in
                    ([word] if len(word) <= 2 or word.isascii() else
                     [word[index:index + 2] for index in range(len(word) - 1)])))[:24]
    if keywords:
        related = rows(conn, actor, conversation_id, keywords=keywords)
        seen = {str(row['turn_id']) for row in corpus}
        corpus.extend(row for row in related if str(row['turn_id']) not in seen)
    conn.commit()  # No database lock spans the stateless ranker.
    if not corpus:
        return [], 'empty'
    # Rank bounded chunks; hydrate complete original user turns, so negation or
    # temporal qualifications outside a matched chunk cannot be silently lost.
    chunks = [{'memory_id': row['turn_id'], 'version': offset // 1000 + 1,
               'content': row['question'][offset:offset + 1000], 'source': row}
              for row in corpus for offset in range(0, min(len(row['question']), 4000), 1000)]
    try:
        ranked = rank_documents(query, chunks)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        return [], 'retrieval_unavailable'
    # Include the two latest turns before older lexical hits, so recent
    # corrections/uncertainty are not displaced by a better scoring old statement.
    chosen, seen, size = [], set(), 0
    for row in [*(corpus[:2] if include_recent else []), *(hit['source'] for hit in ranked)]:
        key = str(row['turn_id'])
        if key in seen or size + len(row['question']) > 8000:
            continue
        seen.add(key)
        size += len(row['question'])
        chosen.append(row)
        if len(chosen) == 5:
            break
    return sorted(chosen, key=lambda row: (row['created_at'], str(row['turn_id']))), 'available' if chosen else 'empty'


def extend_context(conn, actor, conversation_id, query, snapshot, history):
    if not enabled() or not conn.execute('SELECT 1 FROM user_accounts WHERE actor_id=%s', (actor,)).fetchone():
        return snapshot, history
    found, status = retrieve(conn, actor, conversation_id, query)
    refs = {str(ref['source_turn_id']): ref for ref in snapshot.get('history_refs', [])}
    for turn in history:
        for ref in (turn.get('answer') or {}).get('history_source_refs') or []:
            refs[str(ref['source_turn_id'])] = ref
    items = list(snapshot['items'])
    for row in found:
        key = str(row['turn_id'])
        refs[key] = merge_reference(refs.get(key), reference(row))
        items.append({'source_kind': 'historical_user_message', 'source_turn_id': str(row['turn_id']),
                      'source_case_id': str(row['case_id']), 'source_recorded_at': row['created_at'].isoformat(),
                      'content': row['question'], 'medical_verification': False, 'requires_reconciliation': True})
    for row in material_history(conn, actor, conversation_id):
        key = str(row['turn_id'])
        refs[key] = merge_reference(refs.get(key), reference(row))
        packet = row['material_context']
        items.append({'source_kind':'historical_material_report','source_turn_id':key,
            'source_case_id':str(row['case_id']),'source_recorded_at':row['report_recorded_at'].isoformat(),
            'content':json.dumps(packet['sections'],ensure_ascii=False),'evidence_refs':packet['evidence_refs'],
            'notice':'此前整理的原材料及核对结果，不是当前病情；保留诊断中的疑似、否定及既往限定，不跨就医事件合并。'})
    snapshot = {**snapshot, 'items': items, 'history_refs': list(refs.values()),
                'allow_suggestions': False,
                'status': 'available' if items else status}
    from .memory_service import validate_context
    validate_context(conn, actor, conversation_id, snapshot)
    conn.commit()
    return snapshot, history


def search(conn, actor, conversation_id, query):
    found, status = retrieve(conn, actor, conversation_id, query, include_recent=not query.strip())
    combined = {str(row['turn_id']):row for row in found}
    needs_material = not query.strip() or re.search(r'历史|以前|之前|上次|记得|过去|记录|诊断|疾病|什么病|病历|治疗|手术|复查|看过|就医|病情|出院|费用|history|diagnosis|previous|treatment',query,re.I)
    for row in material_history(conn,actor,conversation_id) if needs_material else []:
        combined[str(row['turn_id'])] = {**combined.get(str(row['turn_id']),{}),**row}
    found = list(combined.values())
    # Assistant prose is never recycled as a medical source. Original user
    # messages remain searchable even when their old answers are invalidated.
    return {'status': 'found' if found else status,
            'messages': [{**row, 'answer': None} for row in found],
            'memory_consent_version': 0, 'policy_epoch': 0,
            'notice': '历史原话仅用于承接交流；保留人物、时间、否定及不确定性，最新更正优先。不能当作当前诊断或处方。'}
