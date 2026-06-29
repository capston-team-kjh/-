import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_review import (  # noqa: E402
    apply_interval_corrections,
    list_pending,
    pending_path,
    queue_final_review,
)


def _result():
    timeline = []
    for second in range(10):
        state = "drowsy" if second < 5 else "focus"
        timeline.append({"t": second, "state": state, "states": [state], "flags": {"drowsy": state == "drowsy"}})
    return {
        "session_id": "REVIEW_TEST",
        "status": "success",
        "meta": {"duration_sec": 10},
        "summary": {"focus_score": 50, "focus_ratio": 0.5, "drowsy_total_sec": 5},
        "timeline": timeline,
        "events": [{"type": "drowsy", "start_sec": 0, "end_sec": 5}],
    }


class CodexReviewTest(unittest.TestCase):
    def test_manual_interval_correction_recalculates_result(self) -> None:
        result = _result()

        applied = apply_interval_corrections(result, [(0, 5, "focus")])

        self.assertEqual(applied[0]["changed_points"], 5)
        self.assertEqual(result["summary"]["drowsy_total_sec"], 0)
        self.assertEqual(result["summary"]["focus_total_sec"], 10)
        self.assertEqual(result["summary"]["focus_ratio"], 1.0)

    def test_final_result_is_queued_until_codex_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "CODEX_MANUAL_REVIEW_ENABLED": "true",
                "CODEX_MANUAL_REVIEW_DIR": temp_dir,
            }
            with patch.dict(os.environ, env, clear=False):
                result = _result()
                job = {
                    "session_id": "REVIEW_TEST",
                    "user_id": 3,
                    "camera_type": "merged",
                    "mode": "focus_analysis",
                }
                queued = queue_final_review(result, job, "rds")

                self.assertTrue(queued.exists())
                self.assertEqual(list_pending()[0]["session_id"], "REVIEW_TEST")
                envelope = json.loads(pending_path("REVIEW_TEST").read_text(encoding="utf-8"))
                self.assertEqual(envelope["status"], "pending")
                self.assertEqual(envelope["result_sink"], "rds")


if __name__ == "__main__":
    unittest.main()
