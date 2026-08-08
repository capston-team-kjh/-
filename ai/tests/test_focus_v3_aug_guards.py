import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai.focus_v3_aug.guards import (
    LOCK_KEYS,
    GuardViolation,
    assert_test_isolation,
    snapshot_protected,
    verify_experiment_lock,
    verify_protected,
    write_experiment_lock,
)


def complete_lock_fixture():
    state = {key: {'canonical': key} for key in LOCK_KEYS}
    state['validation_metrics'] = {'A': {'macro_f1': 0.2}}
    return state


class GuardTests(unittest.TestCase):
    def test_protected_copy_mutation_is_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'model.onnx'
            path.write_bytes(b'original')
            snapshot = snapshot_protected([path])
            path.write_bytes(b'changed')
            with self.assertRaises(GuardViolation):
                verify_protected(snapshot)

    def test_frozen_test_lineage_is_rejected_from_training(self):
        manifest = {
            'row_count': 1,
            'groups': ['TEST'],
            'rows': [{'original_sample_id': 'T1'}],
        }
        with self.assertRaises(GuardViolation):
            assert_test_isolation(
                manifest,
                [{'split': 'train', 'original_sample_id': 'T1'}],
                [],
            )

    def test_lock_change_invalidates_test(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'experiment-lock.json'
            state = complete_lock_fixture()
            write_experiment_lock(state, path)
            state['validation_metrics']['A']['macro_f1'] = 0.9
            with self.assertRaisesRegex(
                GuardViolation, 'INVALIDATED_LOCK_CHANGED'
            ):
                verify_experiment_lock(path, state)

    def test_every_required_lock_key_is_enforced(self):
        for missing_key in LOCK_KEYS:
            with self.subTest(missing_key=missing_key), TemporaryDirectory() as temp:
                state = complete_lock_fixture()
                del state[missing_key]
                with self.assertRaisesRegex(GuardViolation, missing_key):
                    write_experiment_lock(
                        state, Path(temp) / 'experiment-lock.json'
                    )


if __name__ == '__main__':
    unittest.main()
