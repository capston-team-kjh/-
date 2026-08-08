import unittest
from copy import deepcopy
from unittest.mock import patch

from ai.focus_v3_aug.config import DecisionThresholds, ModelConfig
from ai.focus_v3_aug.experiments import fit_gaussian_nb
from ai.focus_v3_aug.metrics import classification_report, is_improved


FEATURE_NAMES = ('f1', 'f2')
CLASS_ORDER = ('drowsy', 'focus', 'gaze_down', 'gaze_side')


def rows_with_labels(labels):
    return [
        {
            'sample_id': f'S{index}',
            'label': label,
            'f1': float(index),
            'f2': float(index + 1),
        }
        for index, label in enumerate(labels)
    ]


def metric_pair():
    per_class = {
        label: {
            'precision': 0.6,
            'recall': 0.6,
            'f1': 0.6,
            'support': 10,
        }
        for label in CLASS_ORDER
    }
    baseline_split = {
        'macro_f1': 0.50,
        'balanced_accuracy': 0.50,
        'focus_recall': 0.50,
        'focus_precision': 0.60,
        'prediction_concentration': 0.50,
        'per_class': deepcopy(per_class),
    }
    candidate_split = {
        'macro_f1': 0.52,
        'balanced_accuracy': 0.52,
        'focus_recall': 0.70,
        'focus_precision': 0.60,
        'prediction_concentration': 0.50,
        'per_class': deepcopy(per_class),
    }
    return (
        {'validation': deepcopy(baseline_split), 'test': deepcopy(baseline_split)},
        {
            'validation': deepcopy(candidate_split),
            'test': deepcopy(candidate_split),
        },
    )


class ExperimentTests(unittest.TestCase):
    @patch('ai.focus_v3_aug.experiments.compute_sample_weight')
    def test_each_fit_recomputes_balanced_weights_from_its_labels(self, compute):
        compute.return_value = [1.0, 1.0, 1.0, 1.0]
        labels = ['focus', 'focus', 'drowsy', 'gaze_side']
        fit_gaussian_nb(
            rows_with_labels(labels), ModelConfig(), FEATURE_NAMES
        )
        compute.assert_called_once_with(
            'balanced', ['focus', 'focus', 'drowsy', 'gaze_side']
        )

    def test_confusions_and_prediction_concentration_are_reported(self):
        report = classification_report(
            ['focus', 'focus', 'drowsy'],
            ['gaze_down', 'focus', 'gaze_down'],
            CLASS_ORDER,
        )
        self.assertEqual(report.confusion_raw['focus']['gaze_down'], 1)
        self.assertAlmostEqual(
            report.confusion_row_normalized['focus']['gaze_down'], 0.5
        )
        self.assertEqual(report.dominant_prediction_class, 'gaze_down')
        self.assertAlmostEqual(report.prediction_concentration, 2 / 3)

    def test_validation_class_recall_drop_blocks_improved(self):
        baseline, candidate = metric_pair()
        candidate['validation']['per_class']['gaze_side']['recall'] = 0.53
        self.assertFalse(
            is_improved(candidate, baseline, DecisionThresholds()).passed
        )

    def test_focus_recall_gain_with_precision_collapse_is_not_improved(self):
        baseline, candidate = metric_pair()
        candidate['validation']['focus_precision'] = 0.53
        self.assertFalse(
            is_improved(candidate, baseline, DecisionThresholds()).passed
        )


if __name__ == '__main__':
    unittest.main()
