import unittest
import json
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.eval_cli import evaluate, summarize_blind


def run(facts=(), insights=(), status='completed', insight_status='completed'):
    return {'status': status, 'facts': list(facts), 'insights': list(insights),
            'stage_results': {'insights': {'status': insight_status, 'model_status': 'completed'}}}


def fact(kind, value, assertion='present'):
    return {'fact_type': kind, 'value': value, 'status': 'observed', 'assertion': assertion}


def score(reader, blind, warmth=5, action=5):
    return {'读者编号': reader, '盲评编号': blind, '温度感(1-5)': str(warmth),
            '可行动性(1-5)': str(action), '医学事实错误(有/无/不确定)': '无'}


class EvaluationTests(unittest.TestCase):
    def test_failed_and_missing_runs_remain_in_denominator(self):
        golds = [{'case_id': cid, 'gold': {'stay_days': 3.5},
                  'labels': {'EXP_TERMINOLOGY_BARRIER': {'present': False, 'severity': None}}}
                 for cid in ('good', 'failed', 'missing')]
        result = evaluate(golds, {'good': run([fact('stay_days', 3.5)]), 'failed': run(status='failed')})
        self.assertEqual(result['kr1']['micro']['fn'], 2)
        self.assertEqual(result['kr1']['micro']['f1'], 0.5)
        self.assertEqual(result['kr1']['macro_case_f1'], 1 / 3)
        self.assertEqual(result['kr1']['missing_field_rate'], 2 / 3)
        self.assertEqual(result['kr2']['agreement'], 1 / 3)

    def test_wrong_scalar_counts_false_positive_and_false_negative(self):
        result = evaluate([{'case_id': 'c', 'gold': {'stay_days': 3.5}}], {'c': run([fact('stay_days', 3)])})
        self.assertEqual(result['kr1']['micro']['tp'], 0)
        self.assertEqual(result['kr1']['micro']['fp'], 1)
        self.assertEqual(result['kr1']['micro']['fn'], 1)
        self.assertEqual(result['kr1']['missing_field_rate'], 0)

    def test_report_review_does_not_erase_completed_extraction(self):
        gold = {'case_id': 'c', 'gold': {'stay_days': 3.5}}
        pending = run([fact('stay_days', 3.5)], status='waiting_review', insight_status='waiting_review')
        pending['stage_results']['extract'] = {'status': 'completed'}
        result = evaluate([gold], {'c': pending})
        self.assertEqual(result['kr1']['micro']['f1'], 1)
        self.assertEqual(result['missing_or_failed_runs'], 0)
        self.assertEqual(result['run_status_counts'], {'waiting_review': 1})

    def test_money_currency_is_not_discarded_to_create_false_match(self):
        gold = {'case_id': 'c', 'gold': {'total_cost_minor': 12000}}
        result = evaluate([gold], {'c': run([fact('total_cost', {'amount_minor': 12000, 'currency': 'USD'})])})
        self.assertEqual(result['kr1']['micro']['tp'], 0)
        self.assertEqual(result['kr1']['micro']['fn'], 1)

    def test_uncertainty_and_source_missing_are_explicitly_excluded(self):
        gold = {'case_id': 'c', 'gold': {'stay_days': 3.5, 'self_paid_minor': None},
                '_unsure': ['stay_days'], '_labels_unsure': ['EXP_TERMINOLOGY_BARRIER'],
                'labels': {'EXP_TERMINOLOGY_BARRIER': {'present': True, 'severity': 'low'}}}
        result = evaluate([gold], {'c': run([fact('stay_days', 3)])})
        self.assertIsNone(result['kr1']['micro']['f1'])
        self.assertEqual(result['kr1']['per_field']['stay_days']['uncertain'], 1)
        self.assertEqual(result['kr1']['per_field']['self_paid_minor']['source_missing'], 1)
        self.assertIsNone(result['kr2']['agreement'])

    def test_split_duplicates_and_assertion_changes_cannot_inflate_entity_tp(self):
        gold = {'case_id': 'c', 'gold': {'diagnoses': ['疑似肺炎', '甲乙']}}
        result = evaluate([gold], {'c': run([fact('diagnosis', '肺炎'), fact('diagnosis', '甲'),
                                           fact('diagnosis', '乙'), fact('diagnosis', '甲')])})
        self.assertEqual(result['kr1']['micro']['tp'], 0)
        self.assertEqual(result['kr1']['micro']['fp'], 4)
        self.assertEqual(result['kr1']['micro']['fn'], 2)
        exact = evaluate([{'case_id': 'c', 'gold': {'diagnoses': ['疑似肺炎']}}],
                         {'c': run([fact('diagnosis', '肺炎', 'suspected')] * 2)})
        self.assertEqual(exact['kr1']['micro']['tp'], 1)
        self.assertEqual(exact['kr1']['micro']['fp'], 1)

    def test_pending_label_is_abstention_not_automatic_correct(self):
        label = 'CLIN_MEDICATION_CONTEXT_REVIEW'
        gold = {'case_id': 'c', 'gold': {}, 'labels': {label: {'present': True, 'severity': 'high'}}}
        pending = {'label': label, 'severity': 'high', 'judgment_status': 'candidate', 'review_status': 'pending'}
        result = evaluate([gold], {'c': run(insights=[pending])})
        self.assertEqual(result['kr2']['agreement'], 0)
        self.assertEqual(result['kr2']['automatic_coverage'], 0)
        self.assertEqual(result['kr2']['per_label'][label]['fn'], 1)

    def test_disabled_semantic_detector_is_not_an_automatic_negative(self):
        label = 'CLIN_MEDICATION_CONTEXT_REVIEW'
        gold = {'case_id': 'c', 'gold': {}, 'labels': {label: {'present': False, 'severity': None}}}
        disabled = run()
        disabled['stage_results']['insights']['model_status'] = 'not_configured'
        result = evaluate([gold], {'c': disabled})
        self.assertEqual(result['kr2']['agreement'], 0)
        self.assertEqual(result['kr2']['per_label'][label]['abstained'], 1)

    def test_cli_writes_frozen_input_hashes_and_keeps_missing_run(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / 'gold').mkdir()
            (base / 'runs').mkdir()
            gold = {'case_id': 'c', 'gold': {'stay_days': 3.5}}
            (base / 'gold/c.json').write_text(json.dumps(gold), encoding='utf-8')
            manifest = dict.fromkeys(('code_version', 'model_id', 'prompt_version', 'schema_version',
                'knowledge_version', 'policy_version', 'dataset_origin', 'execution_mode',
                'annotation_origin', 'patient_group_hash'), 'synthetic-test')
            (base / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            output = base / 'result.json'
            result = subprocess.run([sys.executable, '-m', 'scripts.eval_cli', '--manifest',
                str(base / 'manifest.json'), '--output', str(output), 'fields', '--gold-dir',
                str(base / 'gold'), '--runs-dir', str(base / 'runs')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['kr1']['micro']['fn'], 1)
            self.assertEqual(saved['manifest'], manifest)
            self.assertEqual(len(saved['input_sha256']), 2)
            self.assertTrue(all(len(v) == 64 for v in saved['input_sha256'].values()))
            self.assertFalse(saved['official_metric_verified'])
            rows = [score(f'AI-{i}', 'a') for i in range(3)]
            with (base / 'scores.csv').open('w', encoding='utf-8-sig', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (base / 'mapping.json').write_text(json.dumps([{'blind_id': 'a', 'case_id': 'c'}]), encoding='utf-8')
            (base / 'readers.json').write_text(json.dumps({f'AI-{i}': {'type': 'ai'} for i in range(3)}), encoding='utf-8')
            result = subprocess.run([sys.executable, '-m', 'scripts.eval_cli', '--manifest',
                str(base / 'manifest.json'), '--output', str(output), 'blind', '--scores',
                str(base / 'scores.csv'), '--mapping', str(base / 'mapping.json'), '--readers',
                str(base / 'readers.json')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['preview_including_ai']['overall']['warmth']['mean'], 5)
            self.assertFalse(saved['preview_including_ai']['score_targets_met'])
            self.assertFalse(saved['registered_independent_humans']['three_readers_per_report_complete'])

    def test_case_weighting_and_three_registered_humans(self):
        mapping = [{'blind_id': 'a', 'case_id': 'a'}, {'blind_id': 'b', 'case_id': 'b'}]
        readers = {str(i): {'type': 'human', 'independent': True} for i in range(4)}
        rows = [score(str(i), 'a', 5, 5) for i in range(4)] + [score(str(i), 'b', 1, 1) for i in range(3)]
        result = summarize_blind(rows, mapping, readers)['registered_independent_humans']
        self.assertEqual(result['overall']['warmth']['mean'], 3)
        self.assertTrue(result['three_readers_per_report_complete'])
        self.assertFalse(result['score_targets_met'])

    def test_ai_duplicates_invalid_scores_and_missing_reports_never_pass_formal(self):
        mapping = [{'blind_id': 'a', 'case_id': 'a'}, {'blind_id': 'missing', 'case_id': 'b'}]
        rows = [score('AI-1', 'a'), score('human1', 'a'), score('human1', 'a'),
                score('human2', 'a', 'nan'), score('human3', 'a', 6), score('human4', 'unknown')]
        readers = {'AI-1': {'type': 'ai', 'independent': True},
                   **{f'human{i}': {'type': 'human', 'independent': True} for i in range(1, 5)}}
        result = summarize_blind(rows, mapping, readers)
        self.assertEqual(result['invalid_rows']['duplicate_reader_report'], 2)
        self.assertEqual(result['invalid_rows']['invalid_or_unscorable_score'], 2)
        self.assertEqual(result['preview_including_ai']['overall']['warmth']['mean'], 5)
        self.assertIsNone(result['registered_independent_humans']['overall']['warmth']['mean'])
        self.assertFalse(result['registered_independent_humans']['score_targets_met'])
        self.assertEqual(result['registered_independent_humans']['unscored_reports'], 2)


if __name__ == '__main__':
    unittest.main()
