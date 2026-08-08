import unittest
from types import SimpleNamespace

from ai.run_focus_v3_aug import STAGE_ORDER, run_experiment


def config_for_test():
    return SimpleNamespace(run_id='RUN_TEST', expected_test_rows=65)


def dependencies_for_test(*, mutate_lock_before_test=False):
    calls = []
    validation_rows_seen = []

    def execute(stage_name, state):
        calls.append(stage_name)
        if stage_name == 'validation_evaluation':
            validation_rows_seen.extend(state.validation_rows)
        if stage_name == 'frozen_test_evaluation' and mutate_lock_before_test:
            state.test_status = 'INVALIDATED_LOCK_CHANGED'
            state.valid_test_metrics = None
        return state

    return SimpleNamespace(
        execute=execute,
        calls=calls,
        validation_rows_seen=validation_rows_seen,
    )


class PipelineTests(unittest.TestCase):
    def test_stage_order_is_exact(self):
        self.assertEqual(
            STAGE_ORDER,
            (
                'inventory_and_hashes',
                'feature_failure_analysis',
                'label_review',
                'validation_reconstruction',
                'protection_guards',
                'selected_train_pilot_and_parity',
                'full_augmentation',
                'validation_evaluation',
                'experiment_lock',
                'frozen_test_evaluation',
                'post_run_hash_verification',
            ),
        )

    def test_validation_receives_no_test_rows(self):
        dependencies = dependencies_for_test()
        run_experiment(config_for_test(), dependencies)
        self.assertTrue(
            all(
                row['split'] != 'test'
                for row in dependencies.validation_rows_seen
            )
        )

    def test_lock_change_suppresses_test_metrics(self):
        result = run_experiment(
            config_for_test(),
            dependencies_for_test(mutate_lock_before_test=True),
        )
        self.assertEqual(result.test_status, 'INVALIDATED_LOCK_CHANGED')
        self.assertIsNone(result.valid_test_metrics)


if __name__ == '__main__':
    unittest.main()
