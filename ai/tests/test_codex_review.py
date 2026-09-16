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
    create_test_pending_from_committed,
    list_pending,
    pending_path,
    queue_final_review,
)
from codex_sdk_review import (  # noqa: E402
    REVIEW_METADATA_NAME,
    REVIEW_RESULT_NAME,
    apply_review_decision,
    review_session,
    select_representative_frames,
    validate_review_result,
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

    def test_frame_selection_keeps_problem_and_focus_comparison_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            frame_dir = directory / "chunk_1" / "frames"
            frame_dir.mkdir(parents=True)
            frame_rows = []
            for second in range(10):
                path = frame_dir / f"frame_{second:03d}_{second:06d}s.jpg"
                path.write_bytes(b"jpg")
                frame_rows.append(
                    {
                        "path": str(path),
                        "time_sec": second,
                        "global_time_sec": second,
                        "original_state": "drowsy" if second < 5 else "focus",
                    }
                )
            manifest = {"review": {"chunks": [{"chunk_index": 1, "offset_sec": 0, "frames": frame_rows}]}}

            selected, missing = select_representative_frames(directory, manifest, _result(), 4)

            self.assertEqual(missing, 0)
            self.assertEqual(len(selected), 4)
            self.assertIn("drowsy", {row["original_state"] for row in selected})
            self.assertIn("focus", {row["original_state"] for row in selected})

    def test_requeue_test_archives_committed_result_and_marks_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "CODEX_MANUAL_REVIEW_ENABLED": "true",
                "CODEX_MANUAL_REVIEW_DIR": temp_dir,
            }
            with patch.dict(os.environ, env, clear=False):
                result = _result()
                result["session_id"] = 42
                result["codex_manual_review"] = {
                    "chunks": [
                        {
                            "chunk_index": 1,
                            "offset_sec": 0,
                            "frames": [
                                {
                                    "path": str(Path(temp_dir) / "session_42" / "chunk_1" / "frames" / "f.jpg"),
                                    "time_sec": 6,
                                    "global_time_sec": 6,
                                    "original_state": "drowsy",
                                }
                            ],
                        }
                    ]
                }
                queued = queue_final_review(result, {"session_id": 42, "user_id": 3}, "rds")
                directory = Path(temp_dir) / "session_42"
                envelope = json.loads(queued.read_text(encoding="utf-8"))
                envelope["status"] = "committed"
                committed = directory / "committed_result.json"
                committed.write_text(json.dumps(envelope), encoding="utf-8")
                queued.unlink()

                pending = create_test_pending_from_committed(42)

                recreated = json.loads(pending.read_text(encoding="utf-8"))
                manifest = json.loads((directory / "review_manifest.json").read_text(encoding="utf-8"))
                self.assertTrue(recreated["test_pending"]["is_test_pending"])
                self.assertEqual(manifest["status"], "pending")
                self.assertEqual(
                    manifest["review"]["chunks"][0]["frames"][0]["original_state"],
                    "focus",
                )
                self.assertTrue(list(directory.glob("committed_result.pre_sdk_e2e.*.json")))

    def test_validation_allows_only_high_confidence_for_auto_apply(self) -> None:
        frames = [
            {
                "label": "chunk_1/frames/frame_001.jpg",
                "global_time_sec": 1.0,
                "original_state": "drowsy",
            }
        ]
        decision = {
            "session_id": 42,
            "review_status": "corrected",
            "final_focus_score": 75,
            "corrections": [
                {
                    "start_sec": 0,
                    "end_sec": 2,
                    "original_state": "drowsy",
                    "corrected_state": "focus",
                    "reason": "eyes are visibly open",
                    "confidence": "medium",
                    "evidence_frames": ["chunk_1/frames/frame_001.jpg"],
                }
            ],
            "summary_reason": "uncertain correction",
        }

        validation = validate_review_result(decision, 42, _result(), frames)

        self.assertEqual(validation["effective_status"], "needs_manual_check")
        self.assertEqual(validation["auto_corrections"], [])
        self.assertEqual(len(validation["manual_corrections"]), 1)

    def test_sdk_review_resumes_thread_and_applies_valid_high_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "CODEX_MANUAL_REVIEW_ENABLED": "true",
                "CODEX_MANUAL_REVIEW_DIR": temp_dir,
            }
            with patch.dict(os.environ, env, clear=False):
                result = _result()
                result["session_id"] = 42
                result["codex_manual_review"] = {
                    "chunks": [
                        {
                            "chunk_index": 1,
                            "offset_sec": 0,
                            "frames": [],
                        }
                    ]
                }
                queue_final_review(result, {"session_id": 42, "user_id": 3}, "rds")
                directory = Path(temp_dir) / "session_42"
                frame_dir = directory / "chunk_1" / "frames"
                frame_dir.mkdir(parents=True)
                frame = frame_dir / "frame_001_000001s.jpg"
                frame.write_bytes(b"jpg")
                manifest_file = directory / "review_manifest.json"
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest["thread_id"] = "thread-existing"
                manifest["review"]["chunks"][0]["frames"] = [
                    {
                        "path": str(frame),
                        "time_sec": 1,
                        "global_time_sec": 1,
                        "original_state": "drowsy",
                    }
                ]
                manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
                decision = {
                    "session_id": 42,
                    "review_status": "corrected",
                    "final_focus_score": 60,
                    "corrections": [
                        {
                            "start_sec": 0,
                            "end_sec": 2,
                            "original_state": "drowsy",
                            "corrected_state": "focus",
                            "reason": "eyes are visibly open",
                            "confidence": "high",
                            "evidence_frames": ["chunk_1/frames/frame_001_000001s.jpg"],
                        }
                    ],
                    "summary_reason": "clear false positive",
                }

                def fake_bridge(request):
                    self.assertEqual(request["thread_id"], "thread-existing")
                    self.assertEqual(request["image_paths"], [str(frame.resolve())])
                    return {
                        "thread_id": "thread-existing",
                        "final_response": json.dumps(decision),
                        "usage": None,
                    }

                with patch("codex_sdk_review._run_sdk_bridge", side_effect=fake_bridge):
                    reviewed = review_session(42)
                applied = apply_review_decision(42)

                self.assertEqual(reviewed["validation"]["effective_status"], "corrected")
                self.assertEqual(applied["corrections"][0]["changed_points"], 2)
                self.assertEqual(applied["final_score"], 75)
                self.assertTrue((directory / REVIEW_RESULT_NAME).exists())
                self.assertTrue((directory / REVIEW_METADATA_NAME).exists())


if __name__ == "__main__":
    unittest.main()
