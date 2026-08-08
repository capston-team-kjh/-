import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.focus_v3_aug.config import create_run_directory, default_config
from ai.focus_v3_aug.lineage import derived_sample_id, original_sample_id


class ConfigLineageTests(unittest.TestCase):
    def test_run_directory_is_new_and_cannot_be_reused(self):
        with TemporaryDirectory() as temp:
            config = default_config(
                Path('.'), Path('baseline'), Path(temp), run_id='RUN_001'
            )
            run_dir = create_run_directory(config)
            self.assertTrue(run_dir.is_dir())
            with self.assertRaises(FileExistsError):
                create_run_directory(config)

    def test_ids_are_canonical_and_parameter_sensitive(self):
        row = {
            'source_sha256': 'abc',
            'source_group_id': 'G1',
            'timestamp_ms': '1000',
            'label': 'focus',
            'label_source': 'human.csv',
        }
        original = original_sample_id(row)
        same = original_sample_id(dict(reversed(list(row.items()))))
        bright = derived_sample_id(
            original, 'brightness', {'factor': 1.1}, 20260808
        )
        dark = derived_sample_id(
            original, 'brightness', {'factor': 0.9}, 20260808
        )
        self.assertEqual(original, same)
        self.assertEqual(len(original), hashlib.sha256().digest_size * 2)
        self.assertNotEqual(bright, dark)


if __name__ == '__main__':
    unittest.main()
