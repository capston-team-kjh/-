import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.focus_v3_aug.config import DecisionThresholds
from ai.focus_v3_aug.reporting import (
    build_final_diagnosis,
    write_final_reports,
)


class ReportingTests(unittest.TestCase):
    def test_validation_and_test_are_separate(self):
        report = {
            'experiments': {
                'A': {
                    'validation': {'macro_f1': 0.3},
                    'test': {'macro_f1': 0.2},
                }
            },
            'decision': {
                'decision': 'NO_MEANINGFUL_CHANGE',
                'primary_cause': 'small_delta',
                'secondary_evidence': [],
                'limitations': ['single_test_group'],
            },
        }
        with TemporaryDirectory() as temp:
            paths = write_final_reports(Path(temp), report)
            document = json.loads(paths['json'].read_text(encoding='utf-8'))
            self.assertIn('validation', document['experiments']['A'])
            self.assertIn('test', document['experiments']['A'])
            self.assertNotEqual(
                document['experiments']['A']['validation'],
                document['experiments']['A']['test'],
            )

    def test_final_cause_is_structured(self):
        evidence = {
            'execution_failed': False,
            'needs_review': False,
            'degraded': False,
            'improved_gate': False,
            'label_problem_score': 0.1,
            'feature_problem_score': 0.9,
            'split_problem_score': 0.3,
            'imbalance_problem_score': 0.2,
        }
        result = build_final_diagnosis(evidence, DecisionThresholds())
        self.assertEqual(result.decision, 'FEATURE_PROBLEM')
        self.assertTrue(result.primary_cause)
        self.assertIsInstance(result.secondary_evidence, list)
        self.assertIsInstance(result.limitations, list)


if __name__ == '__main__':
    unittest.main()
