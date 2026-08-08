import unittest

from ai.focus_v3_aug.failure_analysis import analyze_feature_failures
from ai.focus_v3_aug.label_review import priority_from_signals


class AnalysisTests(unittest.TestCase):
    def test_primary_and_additional_failures_are_preserved(self):
        row = {
            'sample_id': 'S1',
            'face_seen': 0.0,
            'pose_seen': 0.0,
            'calibration_valid': 0.0,
            'avg_ear': '',
            'ear_rolling_std': float('nan'),
        }
        names = (
            'avg_ear',
            'ear_rolling_std',
            'face_seen',
            'pose_seen',
            'calibration_valid',
        )
        failure = analyze_feature_failures([row], names)[0]
        self.assertEqual(failure.primary_reason, 'face_detection_failure')
        self.assertIn('pose_detection_failure', failure.additional_reasons)
        self.assertIn('calibration_not_ready', failure.additional_reasons)
        self.assertIn('required_feature_missing', failure.additional_reasons)
        self.assertIn('non_finite_feature', failure.additional_reasons)

    def test_priority_is_not_truth(self):
        result = priority_from_signals(
            strong=2, moderate=0, alternative_label='gaze_down'
        )
        self.assertEqual(result.confidence, 'HIGH')
        self.assertEqual(
            result.priority_semantics, 'human_review_priority_not_truth'
        )

    def test_vector_ready_row_is_not_reclassified_as_unusable(self):
        row = {
            'sample_id': 'S2',
            'vector_ready': 'True',
            'face_seen': 0.0,
            'pose_seen': 0.0,
            'calibration_valid': 1.0,
        }
        failures = analyze_feature_failures(
            [row], ('face_seen', 'pose_seen', 'calibration_valid')
        )
        self.assertEqual(failures, [])


if __name__ == '__main__':
    unittest.main()
