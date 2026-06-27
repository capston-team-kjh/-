from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_import_stubs() -> None:
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: None
    sys.modules.setdefault("boto3", boto3)

    requests = types.ModuleType("requests")
    requests.post = lambda *args, **kwargs: None
    sys.modules.setdefault("requests", requests)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv)

    pymysql = sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
    pymysql.cursors = types.SimpleNamespace(DictCursor=object)
    pymysql.connect = lambda **kwargs: object()


_install_import_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worker  # noqa: E402


class FakeS3Client:
    def download_file(self, bucket: str, key: str, path: str) -> None:
        Path(path).write_bytes(b"fake video")


def _message(**overrides):
    body = {
        "session_id": 12,
        "user_id": 3,
        "s3_bucket": "bucket",
        "s3_key": "uploads/session_12/chunk_1.webm",
        "camera_type": "merged",
        "mode": "focus_analysis",
        "chunk_index": 1,
        "is_final_chunk": False,
    }
    body.update(overrides)
    return {"Body": json.dumps(body)}


def _analysis_result(duration: int, focus: int, event_start: int | None = None, event_end: int | None = None):
    events = []
    if event_start is not None and event_end is not None:
        events.append({"type": "drowsy", "start_sec": event_start, "end_sec": event_end, "score": 0.9})

    return {
        "session_id": "12",
        "status": "success",
        "meta": {
            "duration_sec": duration,
            "processing_time_sec": 1,
            "camera_type": "merged",
            "version": "test",
        },
        "summary": {
            "focus_ratio": 0.0,
            "focus_total_sec": focus,
            "bad_posture_ratio": 0.0,
            "bad_posture_total_sec": 0,
            "bad_posture_count": 0,
            "away_total_sec": 0,
            "away_count": 0,
            "drowsy_total_sec": 0,
            "drowsy_count": 0,
            "absent_total_sec": 0,
            "absent_count": 0,
        },
        "timeline": [
            {"t": 0, "state": "focus", "states": ["focus"]},
            {"t": max(duration - 1, 0), "state": "focus", "states": ["focus"]},
        ],
        "events": events,
    }


class WorkerMessageValidationTest(unittest.TestCase):
    def test_missing_chunk_index_fails_validation(self) -> None:
        body = json.loads(_message()["Body"])
        body.pop("chunk_index")

        with self.assertRaises(worker.MessageValidationError) as ctx:
            worker._parse_message_body({"Body": json.dumps(body)})

        self.assertIn("chunk_index", str(ctx.exception))

    def test_focus_analysis_mode_is_allowed(self) -> None:
        job = worker._parse_message_body(_message(is_final_chunk=True))

        self.assertEqual(job["mode"], "focus_analysis")
        self.assertEqual(job["chunk_index"], 1)
        self.assertTrue(job["is_final_chunk"])


class WorkerFeedbackRowTest(unittest.TestCase):
    def test_feedback_row_keeps_only_feedback_text(self) -> None:
        result = {
            "time_patterns": {
                "interval_sec": 300,
                "best_segment": {
                    "start_sec": 0,
                    "end_sec": 300,
                    "focus_ratio": 0.8,
                },
                "worst_segment": {
                    "start_sec": 300,
                    "end_sec": 600,
                    "focus_ratio": 0.5,
                },
                "insights": ["lowest focus window", "drowsy was frequent"],
            },
            "feedback": {
                "summary_text": "overall summary",
                "weak_point": "weak point",
                "recommendation": "recommendation",
            },
        }

        row = worker._feedback_row_from_result("S001", result)

        self.assertEqual(
            row["session_id"],
            "S001",
        )
        self.assertEqual(row["feedback_text"], "lowest focus window\ndrowsy was frequent")
        self.assertIsNotNone(row["personal_feedback"])
        self.assertEqual(row["feedback_source"], "rule_based")
        self.assertEqual(row["feedback_version"], "feedback-v1")


class WorkerChunkFlowTest(unittest.TestCase):
    def test_non_final_chunk_only_writes_temp_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "AI_CHUNK_RESULT_DIR": str(Path(temp_dir) / "chunks"),
                "S3_DOWNLOAD_DIR": str(Path(temp_dir) / "downloads"),
                "AI_FEEDBACK_DISABLE_API": "true",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch.object(worker, "_run_existing_analysis", return_value=_analysis_result(10, 10)):
                    with patch.object(worker, "_save_result_to_rds") as save_result:
                        self.assertTrue(worker._process_message(FakeS3Client(), _message(), "rds"))

            result_path = Path(temp_dir) / "chunks" / "session_12" / "chunk_1_result.json"
            self.assertTrue(result_path.exists())
            save_result.assert_not_called()

    def test_final_chunk_merges_all_chunks_and_saves_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "AI_CHUNK_RESULT_DIR": str(Path(temp_dir) / "chunks"),
                "S3_DOWNLOAD_DIR": str(Path(temp_dir) / "downloads"),
                "AI_FEEDBACK_DISABLE_API": "true",
            }
            with patch.dict(os.environ, env, clear=False):
                first_job = worker._parse_message_body(_message())
                worker._save_chunk_result(first_job, _analysis_result(10, 10, 8, 10))

                saved_results = []

                def capture_save(result):
                    saved_results.append(result)

                final_message = _message(
                    s3_key="uploads/session_12/chunk_2.webm",
                    chunk_index=2,
                    is_final_chunk=True,
                )
                with patch.object(worker, "_run_existing_analysis", return_value=_analysis_result(5, 5, 0, 2)):
                    with patch.object(worker, "_save_result_to_rds", side_effect=capture_save):
                        self.assertTrue(worker._process_message(FakeS3Client(), final_message, "rds"))

            self.assertEqual(len(saved_results), 1)
            final_result = saved_results[0]
            self.assertEqual(final_result["meta"]["duration_sec"], 15)
            self.assertEqual(final_result["summary"]["focus_ratio"], 1.0)
            self.assertIn("personal_feedback", final_result)
            self.assertEqual(final_result["personal_feedback"]["main_problem"], "집중 패턴 안정")
            self.assertIn({"t": 10.0, "state": "focus", "states": ["focus"]}, final_result["timeline"])
            self.assertEqual(final_result["events"][0]["start_sec"], 8)
            self.assertEqual(final_result["events"][0]["end_sec"], 12.0)

    def test_backend_payload_includes_personal_feedback(self) -> None:
        result = _analysis_result(10, 8)
        result["personal_feedback"] = {
            "main_problem": "시선이탈 증가",
            "reason": "시선이탈 시간이 많았습니다.",
            "feedback": "학습 자료를 정면에 배치하는 것이 좋습니다.",
            "next_action": "주변 알림을 줄여보세요.",
            "worst_segments": [],
        }
        job = worker._parse_message_body(_message(is_final_chunk=True))

        payload = worker._build_backend_result_payload(result, job)

        self.assertIn("personal_feedback", payload)
        self.assertEqual(payload["personal_feedback"]["main_problem"], "시선이탈 증가")
        self.assertEqual(payload["feedback_source"], "rule_based")
        self.assertEqual(payload["feedback_version"], "feedback-v1")

    def test_missing_rds_env_reports_required_variable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                worker._rds_connection()

        self.assertIn("RDS_HOST", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
