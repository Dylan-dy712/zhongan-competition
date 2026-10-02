"""Internal, exact-match KR1/KR2 scoring and registered-human KR3 aggregation.

Inputs are authorized files outside Git. Failed/missing runs remain in denominators.
No fuzzy matching, model self-scoring, or claim of official metric equivalence.
"""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from statistics import mean, pstdev

FIELDS = ('hospital', 'admission_date', 'discharge_date', 'stay_days',
          'total_cost_minor', 'self_paid_minor', 'diagnoses', 'procedures', 'medications')
SETS = {'diagnoses', 'procedures', 'medications'}
FACT_FIELDS = {'diagnosis': 'diagnoses', 'surgery': 'procedures', 'medication': 'medications',
               'stay_days': 'stay_days', 'total_cost': 'total_cost_minor'}
LABELS = ('CLIN_MEDICATION_CONTEXT_REVIEW', 'CLIN_EXAM_JUSTIFICATION_REVIEW',
          'COST_SELF_PAY_DEVIATION', 'COST_AMOUNT_RECONCILIATION',
          'EXP_TERMINOLOGY_BARRIER', 'EXP_DISCHARGE_GUIDANCE_GAP')
POLICY = 'internal-exact-case-weighted-v1'


def prf(tp, fp, fn):
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def entity(value):
    assertion = value.get('assertion', 'present') if isinstance(value, dict) else 'present'
    text = value['value'] if isinstance(value, dict) else value
    if not isinstance(text, str) or not text.strip():
        raise ValueError('entity requires a nonempty string')
    text = re.sub(r'\s+', '', text)
    if not isinstance(value, dict):
        for prefix, state in [('疑似', 'suspected'), ('考虑', 'suspected'), ('待排', 'suspected'),
                              ('未见', 'negated'), ('否认', 'negated'), ('既往', 'historical')]:
            if text.startswith(prefix):
                text, assertion = text[len(prefix):], state
                break
    return text, assertion


def predictions(run):
    """Consume current API facts. No guessed hospital/date/self-pay from other fields."""
    if run is None or not (run.get('status') == 'completed' or
            (run.get('status') == 'waiting_review' and
             run.get('stage_results', {}).get('extract', {}).get('status') == 'completed')):
        return {}, False
    values = {key: [] for key in SETS}
    scalars = {}
    for fact in run['facts']:
        field = FACT_FIELDS.get(fact['fact_type'])
        if field is None or fact['status'] not in ('observed', 'derived'):
            continue
        value = fact['value']
        if value is None:
            continue
        if field in SETS:
            values[field].append(entity({'value': value, 'assertion': fact['assertion']}))
        else:
            if field == 'total_cost_minor':
                if value.get('currency') != 'CNY':
                    continue
                value = value['amount_minor']
            scalars.setdefault(field, []).append(value)
    for field, items in scalars.items():
        # Multiple differing scalar facts are unresolved, not cherry-picked minima.
        if all(item == items[0] for item in items):
            values[field] = items[0]
    return values, True


def evaluate(golds, runs):
    per_field = {key: Counter(dict.fromkeys(('tp', 'fp', 'fn', 'opportunities', 'automatic',
                    'missing', 'wrong_value', 'uncertain', 'unannotated', 'source_missing'), 0)) for key in FIELDS}
    per_label = {key: Counter(dict.fromkeys(('tp', 'fp', 'fn', 'tn', 'opportunities', 'automatic',
                    'abstained', 'uncertain', 'gold_positive', 'gold_negative', 'agreements',
                    'severity_total', 'severity_agree'), 0)) for key in LABELS}
    cases, field_f1s = [], []
    for gold in golds:
        cid = gold['case_id']
        run = runs.get(cid)
        pred, completed = predictions(run)
        totals = Counter()
        excluded = set(gold.get('_unsure', []))
        excluded_labels = set(gold.get('_labels_unsure', []))
        if not excluded <= set(FIELDS) or not excluded_labels <= set(LABELS):
            raise ValueError('unknown uncertainty mask entry')
        for field in FIELDS:
            count = per_field[field]
            if field in excluded:
                count['uncertain'] += 1
                continue
            if field not in gold['gold']:
                count['unannotated'] += 1
                continue
            expected = gold['gold'][field]
            if expected is None:
                count['source_missing'] += 1
                continue
            count['opportunities'] += 1
            count['automatic'] += int(completed)
            if field in SETS:
                if not isinstance(expected, list):
                    raise ValueError('gold entity field requires an array')
                expected = Counter(entity(item) for item in expected)
                if any(n > 1 for n in expected.values()):
                    raise ValueError('duplicate gold entity')
                actual = Counter(pred.get(field, []))
                tp = sum((expected & actual).values())
                fp, fn = sum(actual.values()) - tp, sum(expected.values()) - tp
                missing = int(bool(expected) and not actual)
            else:
                actual = pred.get(field)
                tp = int(actual == expected)
                fp, fn = int(actual is not None and not tp), int(not tp)
                missing = int(actual is None)
            scores = {'tp': tp, 'fp': fp, 'fn': fn, 'missing': missing,
                      'wrong_value': int(bool(fp) and bool(fn))}
            count.update(scores)
            totals.update(scores)
        f1 = prf(totals['tp'], totals['fp'], totals['fn'])['f1']
        if f1 is not None:
            field_f1s.append(f1)
        stages = (run or {}).get('stage_results', {})
        insight_complete = completed and stages.get('insights', {}).get('status') == 'completed'
        insight_pred = {}
        for item in (run or {}).get('insights', []):
            if item['label'] not in LABELS:
                raise ValueError('unknown predicted label')
            insight_pred.setdefault(item['label'], []).append(item)
        for label in LABELS:
            count = per_label[label]
            expected = gold.get('labels', {}).get(label)
            if label in excluded_labels or expected is None or expected.get('present') is None:
                count['uncertain'] += 1
                continue
            if not isinstance(expected['present'], bool):
                raise ValueError('gold label present must be boolean or null')
            count['opportunities'] += 1
            positive = expected['present']
            count['gold_positive' if positive else 'gold_negative'] += 1
            items = insight_pred.get(label, [])
            decided = insight_complete and all(i['judgment_status'] == 'supported' and
                       i['review_status'] not in ('pending', 'rejected') for i in items) and (
                       bool(items) or stages['insights'].get('model_status') == 'completed')
            if not decided:
                count['abstained'] += 1
                count['fn'] += int(positive)
                continue
            count['automatic'] += 1
            predicted = bool(items)
            count['tp' if positive and predicted else 'fn' if positive else 'fp' if predicted else 'tn'] += 1
            count['agreements'] += int(positive == predicted)
            if positive and predicted:
                count['severity_total'] += 1
                count['severity_agree'] += int(len({i['severity'] for i in items}) == 1 and
                                              items[0]['severity'] == expected['severity'])
        cases.append({'case_id': cid, 'run_status': (run or {}).get('status', 'missing'), **prf(
                      totals['tp'], totals['fp'], totals['fn'])})
    ftotal = sum(per_field.values(), Counter())
    ltotal = sum(per_label.values(), Counter())
    def ratio(count, numerator, denominator):
        return count[numerator] / count[denominator] if count[denominator] else None
    return {'policy_version': POLICY, 'official_metric_verified': False, 'case_count': len(cases),
            'missing_or_failed_runs': sum(c['run_status'] in ('missing', 'failed') for c in cases),
            'run_status_counts': dict(Counter(c['run_status'] for c in cases)),
            'kr1': {'micro': prf(ftotal['tp'], ftotal['fp'], ftotal['fn']),
                    'scored_case_count': len(field_f1s),
                    'field_opportunities': ftotal['opportunities'],
                    'macro_case_f1': mean(field_f1s) if field_f1s else None,
                    'macro_field_f1': mean(v for c in per_field.values() if
                        (v := prf(c['tp'], c['fp'], c['fn'])['f1']) is not None) if
                        any(c['tp'] + c['fp'] + c['fn'] for c in per_field.values()) else None,
                    'missing_field_rate': ratio(ftotal, 'missing', 'opportunities'),
                    'automatic_run_coverage': ratio(ftotal, 'automatic', 'opportunities'),
                    'per_field': {k: {**c, **prf(c['tp'], c['fp'], c['fn'])} for k, c in per_field.items()}},
            'kr2': {'agreement': ratio(ltotal, 'agreements', 'opportunities'),
                    'label_opportunities': ltotal['opportunities'],
                    'automatic_coverage': ratio(ltotal, 'automatic', 'opportunities'),
                    'per_label': {k: {**c, **prf(c['tp'], c['fp'], c['fn']),
                        'agreement': ratio(c, 'agreements', 'opportunities'),
                        'severity_agreement': ratio(c, 'severity_agree', 'severity_total'),
                        'negative_proportion': ratio(c, 'gold_negative', 'opportunities')}
                        for k, c in per_label.items()}}, 'per_case': cases}


def summarize_blind(rows, mapping, readers):
    ids = [item['blind_id'] for item in mapping]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate blind ID')
    known = {item['blind_id']: item for item in mapping}
    keys = Counter((row.get('读者编号'), row.get('盲评编号')) for row in rows)
    accepted, invalid = {}, Counter()
    for row in rows:
        reader, blind = row.get('读者编号'), row.get('盲评编号')
        if blind not in known or not reader:
            invalid['unknown_identity'] += 1
            continue
        if keys[reader, blind] != 1:
            invalid['duplicate_reader_report'] += 1
            continue
        try:
            warmth, action = float(row['温度感(1-5)']), float(row['可行动性(1-5)'])
            if not all(math.isfinite(v) and 1 <= v <= 5 for v in (warmth, action)):
                raise ValueError('score out of range')
        except (KeyError, TypeError, ValueError):
            invalid['invalid_or_unscorable_score'] += 1
            continue
        error = row.get('医学事实错误(有/无/不确定)')
        if error not in ('有', '无', '不确定'):
            invalid['missing_medical_flag'] += 1
            continue
        info = readers.get(reader, {})
        human = info.get('type') == 'human' and info.get('independent') is True
        accepted.setdefault(blind, []).append({'human': human, 'warmth': warmth,
                                              'actionability': action, 'medical_flag': error})
    def aggregate(human_only):
        by_case, reports = {}, {}
        for blind, item in known.items():
            values = [v for v in accepted.get(blind, []) if not human_only or v['human']]
            reports[blind] = {'valid_readers': len(values), 'required_readers': 3,
                             'medical_flags': dict(Counter(v['medical_flag'] for v in values))}
            if values:
                averages = {dim: mean(v[dim] for v in values) for dim in ('warmth', 'actionability')}
                reports[blind].update(averages)
                by_case.setdefault(item['case_id'], []).append(averages)
        cases = {cid: {dim: mean(v[dim] for v in vals) for dim in ('warmth', 'actionability')}
                 for cid, vals in by_case.items()}
        overall = {}
        for dim in ('warmth', 'actionability'):
            vals = [c[dim] for c in cases.values()]
            overall[dim] = {'mean': mean(vals) if vals else None, 'stddev': pstdev(vals) if vals else None,
                            'case_count': len(vals)}
        complete = bool(known) and all(r['valid_readers'] >= 3 for r in reports.values())
        diseases = Counter(known[blind].get('disease_code', 'unknown') for blind in known)
        return {'overall': overall, 'per_report': reports, 'per_case': cases,
                'report_disease_distribution': dict(diseases),
                'three_readers_per_report_complete': complete,
                'unscored_reports': len(known) - sum(bool(r['valid_readers']) for r in reports.values()),
                'score_targets_met': human_only and complete and all(overall[d]['mean'] >= 4 for d in overall)}
    return {'policy_version': POLICY, 'official_metric_verified': False, 'invalid_rows': dict(invalid),
            'preview_including_ai': aggregate(False), 'registered_independent_humans': aggregate(True),
            'medical_review_passed': None}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fields = sub.add_parser('fields')
    fields.add_argument('--gold-dir', required=True)
    fields.add_argument('--runs-dir', required=True)
    blind = sub.add_parser('blind')
    blind.add_argument('--scores', required=True)
    blind.add_argument('--mapping', required=True)
    blind.add_argument('--readers', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    manifest = load(args.manifest)
    required = {'code_version', 'model_id', 'prompt_version', 'schema_version', 'knowledge_version',
                'policy_version', 'dataset_origin', 'execution_mode', 'annotation_origin', 'patient_group_hash'}
    if any(not manifest.get(key) for key in required):
        raise ValueError('frozen manifest is incomplete')
    paths = []
    if args.command == 'fields':
        gold_paths = sorted(Path(args.gold_dir).glob('*.json'))
        run_paths = sorted(Path(args.runs_dir).glob('*.json'))
        if not gold_paths:
            raise ValueError('no gold cases')
        golds = [load(p) for p in gold_paths]
        loaded = [load(p) for p in run_paths]
        if len({g['case_id'] for g in golds}) != len(golds) or len({r['case_id'] for r in loaded}) != len(loaded):
            raise ValueError('duplicate case ID')
        result = evaluate(golds, {r['case_id']: r for r in loaded})
        paths = gold_paths + run_paths
    else:
        with open(args.scores, encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        result = summarize_blind(rows, load(args.mapping), load(args.readers))
        paths = [Path(args.scores), Path(args.mapping), Path(args.readers)]
    result['manifest'] = manifest
    result['input_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths + [Path(args.manifest)]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(f'Internal evaluation written to {args.output}; official metrics unverified.')


if __name__ == '__main__':
    main()
