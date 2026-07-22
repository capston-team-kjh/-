from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from evaluation import EvaluationError, evaluate
except ModuleNotFoundError:
    from ai.evaluation import EvaluationError, evaluate


ROOT = Path(__file__).resolve().parents[2]


class EvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prediction = json.loads(
            (ROOT / "predictions" / "session_001_result.json").read_text(encoding="utf-8")
        )
        cls.label = json.loads(
            (ROOT / "labels" / "session_001_labels.json").read_text(encoding="utf-8")
        )

    def test_sample_classification_and_confusion_matrix(self) -> None:
        result = evaluate(self.prediction, self.label)
        classification = result["classification"]

        self.assertEqual(classification["sample_count"], 30)
        self.assertEqual(classification["accuracy"], 0.833333)
        self.assertEqual(classification["averaging"], "macro")
        self.assertEqual(classification["f1"], classification["macro_f1"])
        self.assertEqual(classification["per_class"]["absent"]["recall"], 0.8)
        self.assertEqual(classification["confusion_matrix"]["focus"]["gaze_side"], 1)

    def test_duration_focus_score_and_processing_metrics(self) -> None:
        result = evaluate(self.prediction, self.label)

        self.assertEqual(result["duration_error"]["mae_sec"], 0.857143)
        self.assertEqual(
            result["duration_error"]["per_state"]["absent"]["absolute_error_sec"],
            1.0,
        )
        self.assertEqual(result["focus_score_error"]["mae"], 4.0)
        self.assertEqual(result["focus_score_error"]["rmse"], 4.0)
        self.assertEqual(result["processing_time"]["speed_ratio"], 0.2)
        self.assertEqual(result["processing_time"]["realtime_multiplier"], 5.0)

    def test_event_matching_is_one_to_one(self) -> None:
        result = evaluate(self.prediction, self.label)
        events = result["event_detection"]

        self.assertEqual(events["true_positive"], 5)
        self.assertEqual(events["false_positive"], 2)
        self.assertEqual(events["false_negative"], 0)
        self.assertEqual(events["precision"], 0.714286)
        self.assertEqual(events["recall"], 1.0)
        self.assertEqual(events["f1"], 0.833333)

    def test_point_style_manual_labels_are_supported(self) -> None:
        label = dict(self.label)
        label["timeline"] = [
            {"t": row["t"], "state": row["state"]}
            for row in self.prediction["timeline"]
        ]
        label["human_focus_score"] = 78

        result = evaluate(self.prediction, label)

        self.assertEqual(result["classification"]["accuracy"], 1.0)
        self.assertEqual(result["duration_error"]["mae_sec"], 0.0)

    def test_session_mismatch_is_rejected(self) -> None:
        label = dict(self.label)
        label["session_id"] = "different"

        with self.assertRaises(EvaluationError):
            evaluate(self.prediction, label)


if __name__ == "__main__":
    unittest.main()
