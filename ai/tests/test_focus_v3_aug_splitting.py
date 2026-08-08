import unittest

from ai.focus_v3_aug.config import ValidationConfig
from ai.focus_v3_aug.splitting import select_group_validation


CLASS_ORDER = ('drowsy', 'focus', 'gaze_down', 'gaze_side')


def rows_for_groups(group_labels):
    rows = []
    for group_id, labels in group_labels.items():
        for index, label in enumerate(labels):
            rows.append(
                {
                    'original_sample_id': f'{group_id}-{index}',
                    'source_group_id': group_id,
                    'label': label,
                    'split': 'train' if group_id != 'G6' else 'validation',
                }
            )
    return rows


class SplittingTests(unittest.TestCase):
    def test_rows_from_one_group_never_cross_split(self):
        labels = list(CLASS_ORDER) * 3
        rows = rows_for_groups({f'G{index}': labels for index in range(1, 7)})
        existing = {
            'train_groups': ['G1', 'G2', 'G3', 'G4', 'G5'],
            'validation_groups': ['G6'],
        }
        decision = select_group_validation(rows, existing, ValidationConfig())
        self.assertTrue(
            set(decision.train_groups).isdisjoint(decision.validation_groups)
        )
        self.assertEqual(decision.leakage_check, 'pass')

    def test_inadequate_group_support_keeps_existing_split(self):
        rows = rows_for_groups(
            {
                'G1': ['drowsy'] * 6,
                'G2': ['focus'] * 6,
                'G3': ['gaze_down'] * 6,
                'G6': ['gaze_side'] * 6,
            }
        )
        existing = {
            'train_groups': ['G1', 'G2', 'G3'],
            'validation_groups': ['G6'],
        }
        decision = select_group_validation(rows, existing, ValidationConfig())
        self.assertFalse(decision.reconstructed)
        self.assertIn('insufficient_group_support', decision.limitations)


if __name__ == '__main__':
    unittest.main()
