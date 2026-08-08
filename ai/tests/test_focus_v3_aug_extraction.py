import unittest
from pathlib import Path

from ai.focus_v3_aug.extraction import (
    StreamExtractionRequest,
    compare_parity_rows,
    extract_augmented_stream,
)


FEATURE_NAMES = tuple(f'f{index}' for index in range(34))


def extraction_request(label_seconds, split):
    return StreamExtractionRequest(
        project_root=Path('.'),
        source_path=Path('fixture.mp4'),
        source_sha256='abc',
        source_group_id='G1',
        split=split,
        camera_half='full',
        timeline_ms=tuple(range(0, max(label_seconds) * 1000 + 1, 1000)),
        retain_timestamps_ms=tuple(second * 1000 for second in label_seconds),
        feature_names=FEATURE_NAMES,
        augmentation_type='brightness',
        augmentation_parameters={'factor': 1.1},
        seed=20260808,
    )


class FakeDependencies:
    def process_timeline(self, request):
        return [
            {
                'timestamp_ms': timestamp,
                'features': tuple(float(index) for index in range(34)),
                'vector_ready': True,
            }
            for timestamp in request.timeline_ms
        ]


class ExtractionTests(unittest.TestCase):
    def test_stream_processes_zero_through_last_label_in_order(self):
        request = extraction_request((3, 5), 'train')
        result = extract_augmented_stream(
            request, dependencies=FakeDependencies()
        )
        self.assertEqual(
            result.processed_timestamps_ms,
            (0, 1000, 2000, 3000, 4000, 5000),
        )
        self.assertEqual(len(result.accepted_rows[0]['features']), 34)

    def test_validation_or_test_request_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'selected train'):
            extract_augmented_stream(
                extraction_request((1,), 'validation'),
                dependencies=FakeDependencies(),
            )

    def test_parity_reports_actual_maximum_error(self):
        original = [
            {
                'timestamp_ms': 0,
                'features': (1.0,) * 34,
                'vector_ready': True,
            }
        ]
        candidate = [
            {
                'timestamp_ms': 0,
                'features': (1.0 + 5e-10,) + (1.0,) * 33,
                'vector_ready': True,
            }
        ]
        report = compare_parity_rows(
            original,
            candidate,
            FEATURE_NAMES,
            abs_tol=1e-9,
            rel_tol=1e-9,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.abs_tol, 1e-9)
        self.assertAlmostEqual(report.maximum_absolute_error, 5e-10)

    def test_parity_normalizes_legacy_csv_false_and_missing_values(self):
        original = [
            {
                'timestamp_ms': '0',
                'features': ('',) * 34,
                'vector_ready': 'False',
            }
        ]
        candidate = [
            {
                'timestamp_ms': 0,
                'features': (None,) * 34,
                'vector_ready': False,
            }
        ]
        report = compare_parity_rows(
            original,
            candidate,
            FEATURE_NAMES,
            abs_tol=1e-9,
            rel_tol=1e-9,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.readiness_mismatches, ())


if __name__ == '__main__':
    unittest.main()
