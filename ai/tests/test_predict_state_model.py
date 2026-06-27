from __future__ import annotations

import os
import pickle
import tempfile
import unittest

from ai.focus_ai.predict_state_model import (
    load_state_classifier,
    predict_state,
    predict_state_proba,
)


class FakeClassifier:
    classes_ = ["focus", "gaze_side"]

    def predict_proba(self, rows):
        return [[0.2, 0.8]]


class PredictStateModelTest(unittest.TestCase):
    def test_predicts_highest_probability_state(self) -> None:
        bundle = {
            "model": FakeClassifier(),
            "feature_names": ["face_seen", "gaze_side"],
        }

        probabilities = predict_state_proba(bundle, {"face_seen": 1, "gaze_side": 1})

        self.assertEqual(probabilities, {"focus": 0.2, "gaze_side": 0.8})
        self.assertEqual(predict_state(bundle, {"face_seen": 1, "gaze_side": 1}), "gaze_side")

    def test_load_missing_model_returns_none(self) -> None:
        self.assertIsNone(load_state_classifier("missing_state_classifier.pkl"))

    def test_loads_pickle_bundle(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            pickle.dump({"model": FakeClassifier(), "feature_names": ["face_seen"]}, f)
            path = f.name

        try:
            bundle = load_state_classifier(path)
        finally:
            os.unlink(path)

        self.assertIsInstance(bundle, dict)
        self.assertEqual(predict_state(bundle, {"face_seen": 1}), "gaze_side")


if __name__ == "__main__":
    unittest.main()
