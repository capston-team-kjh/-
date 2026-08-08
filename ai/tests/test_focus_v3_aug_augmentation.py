import unittest

from ai.focus_v3_aug.augmentation import (
    SAFE_KINDS,
    build_minority_plan,
    build_transform_plan,
)
from ai.focus_v3_aug.config import AugmentationConfig
from ai.focus_v3_aug.duplicates import find_duplicates


def labeled_rows(counts):
    rows = []
    for label, count in counts.items():
        rows.extend(
            {
                'original_sample_id': f'{label}-{index}',
                'label': label,
                'split': 'train',
                'f1': float(index),
                'f2': float(index + 1),
            }
            for index in range(count)
        )
    return rows


class AugmentationTests(unittest.TestCase):
    def test_b_assignment_is_deterministic_and_capped_at_one(self):
        rows = labeled_rows({'focus': 4, 'drowsy': 2})
        config = AugmentationConfig()
        first = build_transform_plan(rows, config, SAFE_KINDS, seed=20260808)
        second = build_transform_plan(rows, config, SAFE_KINDS, seed=20260808)
        self.assertEqual(first, second)
        counts = {row['original_sample_id']: 0 for row in rows}
        for request in first:
            counts[request.original_sample_id] += 1
        self.assertLessEqual(max(counts.values()), 1)

    def test_c_stops_at_original_train_median(self):
        rows = labeled_rows(
            {'drowsy': 8, 'focus': 20, 'gaze_down': 2, 'gaze_side': 6}
        )
        plan = build_minority_plan(
            rows, AugmentationConfig(), SAFE_KINDS, seed=20260808
        )
        self.assertEqual(plan.median_count, 7)
        self.assertEqual(plan.targets['gaze_down'], 7)
        self.assertLessEqual(plan.final_requested_counts['gaze_down'], 7)
        self.assertEqual(
            len(plan.requests), len({request.sample_id for request in plan.requests})
        )

    def test_exact_and_near_duplicates_are_distinct(self):
        rows = [
            {
                'sample_id': 'O',
                'original_sample_id': 'O',
                'f1': 1.0,
                'f2': 2.0,
            },
            {
                'sample_id': 'E',
                'original_sample_id': 'O',
                'f1': 1.0,
                'f2': 2.0,
            },
            {
                'sample_id': 'N',
                'original_sample_id': 'O',
                'f1': 1.0 + 5e-10,
                'f2': 2.0,
            },
        ]
        report = find_duplicates(rows, ('f1', 'f2'), 1e-9, 1e-9)
        self.assertEqual(report.exact_count, 1)
        self.assertEqual(report.near_count, 1)


if __name__ == '__main__':
    unittest.main()
