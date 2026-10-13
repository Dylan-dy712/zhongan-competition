import unittest
from scripts.build_quality_demo import build


class QualityDemoTests(unittest.TestCase):
    def test_five_dimensions_three_diseases_five_hospitals_and_two_reasons(self):
        result = build()
        self.assertEqual(result['snapshot']['data_origin'], 'synthetic')
        self.assertIn('虚构', result['disclaimer'])
        for kind, count in [('hospital', 15), ('doctor', 15), ('treatment_plan', 3)]:
            self.assertEqual(sum(p['entity_type'] == kind for p in result['snapshot']['profiles']), count)
        for match in result['matches']:
            self.assertEqual(match['coverage']['five_comparable_hospitals'], 5)
            self.assertEqual(match['coverage']['valid_two_reason_hospitals'], 5)
            self.assertEqual(match['coverage']['ranked_hospitals'], 0)
            for candidate in match['candidates']:
                self.assertEqual(len(candidate['match_reasons']), 2)
                self.assertFalse(candidate['ranking_allowed'])
        self.assertNotEqual(result['matches'][0]['candidates'][0]['match_reasons'],
                            result['matches'][1]['candidates'][0]['match_reasons'])
