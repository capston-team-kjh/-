from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterable


AI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AI_DIR.parent
DEFAULT_REVIEW_DIR = "ai/manual_review_queue"
DEFAULT_REVIEW_FRAMES = 20
LOGGER = logging.getLogger("focusai.codex_review")
VALID_STATES = {
    "focus",
    "absent",
    "drowsy",
    "sleep_suspect",
    "gaze_side",
    "gaze_down",
    "bad_posture",
    "unknown",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def review_enabled() -> bool:
    return _env_bool("CODEX_MANUAL_REVIEW_ENABLED", False)


def review_root() -> Path:
    raw = os.getenv("CODEX_MANUAL_REVIEW_DIR", DEFAULT_REVIEW_DIR).strip() or DEFAULT_REVIEW_DIR
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(value: Any) -> str:
    text = "".join(character if character.isalnum() or character in "._-" else "_" for character in str(value))
    return text.strip("._-") or "unknown"


def session_dir(session_id: Any) -> Path:
    path = review_root() / f"session_{_safe_name(session_id)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_path(session_id: Any) -> Path:
    return session_dir(session_id) / "pending_result.json"


def manifest_path(session_id: Any) -> Path:
    return session_dir(session_id) / "review_manifest.json"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object expected: {path}")
    return value


def _review_frame_count() -> int:
    raw = os.getenv("CODEX_MANUAL_REVIEW_FRAMES", str(DEFAULT_REVIEW_FRAMES))
    try:
        return max(4, int(raw))
    except ValueError:
        return DEFAULT_REVIEW_FRAMES


def prepare_chunk_review(
    job: dict[str, Any],
    video_path: str | Path,
    analysis_result: dict[str, Any],
) -> dict[str, Any]:
    """Persist suspicious-frame samples for Codex without calling an external API."""
    if not review_enabled():
        return analysis_result

    from focus_ai.vision.frame_sampler import extract_frames

    chunk_index = int(job.get("chunk_index", 0))
    output_dir = session_dir(job.get("session_id")) / f"chunk_{chunk_index}" / "frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in output_dir.glob("frame_*.jpg"):
        old_frame.unlink()

    frames = extract_frames(
        video_path,
        analysis_result,
        output_dir,
        _review_frame_count(),
    )
    frame_rows = [
        {
            **frame.prompt_metadata(),
            "path": str(frame.path.resolve()),
            "width": frame.width,
            "height": frame.height,
        }
        for frame in frames
    ]
    chunk_review = {
        "status": "frames_ready",
        "session_id": job.get("session_id"),
        "chunk_index": chunk_index,
        "video_path": str(Path(video_path).resolve()),
        "sampled_frame_count": len(frame_rows),
        "frames": frame_rows,
        "prepared_at_unix": int(time.time()),
    }
    analysis_result["codex_manual_review"] = chunk_review
    _write_json(output_dir.parent / "chunk_manifest.json", chunk_review)
    return analysis_result


def merge_chunk_reviews(chunks: Iterable[tuple[int, float, dict[str, Any]]]) -> dict[str, Any]:
    merged_chunks = []
    total_frames = 0
    for chunk_index, offset_sec, review in chunks:
        frames = []
        for raw_frame in review.get("frames", []) if isinstance(review.get("frames"), list) else []:
            if not isinstance(raw_frame, dict):
                continue
            frame = dict(raw_frame)
            try:
                frame["global_time_sec"] = round(float(frame.get("time_sec", 0)) + offset_sec, 3)
            except (TypeError, ValueError):
                frame["global_time_sec"] = offset_sec
            frames.append(frame)
        total_frames += len(frames)
        merged_chunks.append(
            {
                "chunk_index": chunk_index,
                "offset_sec": offset_sec,
                "video_path": review.get("video_path"),
                "frames": frames,
            }
        )
    return {
        "status": "pending_codex_review",
        "sampled_frame_count": total_frames,
        "chunks": merged_chunks,
        "notes": "Codex가 의심 프레임을 직접 검수한 뒤 커밋해야 RDS에 저장됩니다.",
    }


def queue_final_review(
    final_result: dict[str, Any],
    final_job: dict[str, Any],
    result_sink: str,
) -> Path:
    session_id = final_result.get("session_id") or final_job.get("session_id")
    if session_id is None:
        raise RuntimeError("session_id is required for Codex review")
    envelope = {
        "status": "pending",
        "session_id": session_id,
        "user_id": final_job.get("user_id"),
        "result_sink": result_sink,
        "queued_at_unix": int(time.time()),
        "job": final_job,
        "analysis_result": final_result,
    }
    path = pending_path(session_id)
    _write_json(path, envelope)
    review = final_result.get("codex_manual_review")
    previous_manifest = _read_json(manifest_path(session_id)) if manifest_path(session_id).exists() else {}
    previous_sdk_review = (
        previous_manifest.get("sdk_review")
        if isinstance(previous_manifest.get("sdk_review"), dict)
        else {}
    )
    manifest = {
        "status": "pending",
        "session_id": session_id,
        "result_path": str(path.resolve()),
        "focus_score": (final_result.get("summary") or {}).get("focus_score"),
        "problem_events": [
            event
            for event in final_result.get("events", [])
            if isinstance(event, dict)
            and str(event.get("type") or event.get("event_type"))
            in {"drowsy", "sleep_suspect", "gaze_side", "gaze_down", "bad_posture", "absent", "unknown"}
        ],
        "review": review if isinstance(review, dict) else {},
        "thread_id": previous_manifest.get("thread_id") or previous_sdk_review.get("thread_id"),
    }
    _write_json(manifest_path(session_id), manifest)
    return path


def list_pending() -> list[dict[str, Any]]:
    items = []
    for path in sorted(review_root().glob("session_*/pending_result.json")):
        try:
            envelope = _read_json(path)
        except Exception:
            continue
        if envelope.get("status") == "pending":
            manifest_file = path.parent / "review_manifest.json"
            manifest = _read_json(manifest_file) if manifest_file.exists() else {}
            sdk_review = manifest.get("sdk_review") if isinstance(manifest.get("sdk_review"), dict) else {}
            items.append(
                {
                    "session_id": envelope.get("session_id"),
                    "user_id": envelope.get("user_id"),
                    "path": str(path.resolve()),
                    "queued_at_unix": envelope.get("queued_at_unix"),
                    "review_status": sdk_review.get("status") or manifest.get("status"),
                    "thread_id": manifest.get("thread_id") or sdk_review.get("thread_id"),
                }
            )
    return items


def create_test_pending_from_committed(session_id: Any) -> Path:
    """Requeue a committed session for explicit SDK E2E verification.

    The committed artifact is archived first, the RDS row is not touched here,
    and an existing pending result is never overwritten.
    """
    directory = session_dir(session_id)
    committed = directory / "committed_result.json"
    pending = directory / "pending_result.json"
    manifest_file = directory / "review_manifest.json"
    if pending.exists():
        raise RuntimeError(f"pending_result.json already exists: {pending}")
    if not committed.exists():
        raise RuntimeError(f"committed_result.json is missing: {committed}")
    if not manifest_file.exists():
        raise RuntimeError(f"review_manifest.json is missing: {manifest_file}")

    envelope = _read_json(committed)
    result = envelope.get("analysis_result")
    if envelope.get("status") != "committed" or not isinstance(result, dict):
        raise RuntimeError("committed_result.json is not a valid committed review envelope")
    if str(envelope.get("session_id")) != str(session_id):
        raise RuntimeError("requested session_id does not match committed_result.json")

    created_at = int(time.time())
    backup = directory / f"committed_result.pre_sdk_e2e.{created_at}.json"
    shutil.copy2(committed, backup)
    marker = {
        "is_test_pending": True,
        "purpose": "codex_sdk_e2e_verification",
        "source": str(committed.resolve()),
        "backup": str(backup.resolve()),
        "created_at_unix": created_at,
    }
    envelope["status"] = "pending"
    envelope["queued_at_unix"] = created_at
    envelope.pop("committed_at_unix", None)
    envelope["test_pending"] = marker
    review = result.setdefault("codex_manual_review", {})
    review["status"] = "pending_sdk_e2e_revalidation"
    review["test_pending"] = marker
    envelope["analysis_result"] = result
    _write_json(pending, envelope)

    manifest = _read_json(manifest_file)
    timeline = [row for row in result.get("timeline", []) if isinstance(row, dict)]
    timeline_points = []
    for row in timeline:
        try:
            point = float(row.get("t", row.get("time", row.get("time_sec", 0))))
        except (TypeError, ValueError):
            continue
        timeline_points.append((point, str(row.get("state") or "unknown")))
    manifest_review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    chunks = manifest_review.get("chunks") if isinstance(manifest_review.get("chunks"), list) else []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        offset = float(chunk.get("offset_sec") or 0)
        frames = chunk.get("frames") if isinstance(chunk.get("frames"), list) else []
        for frame in frames:
            if not isinstance(frame, dict) or not timeline_points:
                continue
            try:
                raw_point = frame.get("global_time_sec")
                point = float(raw_point) if raw_point is not None else offset + float(frame.get("time_sec", 0))
            except (TypeError, ValueError):
                continue
            frame["original_state"] = min(timeline_points, key=lambda item: abs(item[0] - point))[1]

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    manifest["status"] = "pending"
    manifest["result_path"] = str(pending.resolve())
    manifest["focus_score"] = summary.get("focus_score")
    manifest["problem_events"] = [
        event
        for event in result.get("events", [])
        if isinstance(event, dict)
        and str(event.get("type") or event.get("event_type"))
        in {"drowsy", "sleep_suspect", "gaze_side", "gaze_down", "bad_posture", "absent", "unknown"}
    ]
    manifest["review"] = manifest_review
    manifest["test_pending"] = marker
    manifest.pop("rds_verification", None)
    _write_json(manifest_file, manifest)
    LOGGER.warning(
        "TEST PENDING CREATED: session_id=%s, source=%s, backup=%s",
        session_id,
        committed,
        backup,
    )
    return pending


def _parse_correction(value: str) -> tuple[float, float, str]:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"correction must be START:END:STATE, got {value!r}")
    start, end = float(parts[0]), float(parts[1])
    state = parts[2].strip()
    if start < 0 or end <= start:
        raise ValueError(f"invalid correction interval: {value!r}")
    if state not in VALID_STATES:
        raise ValueError(f"invalid state {state!r}; expected one of {sorted(VALID_STATES)}")
    return start, end, state


def apply_interval_corrections(
    analysis_result: dict[str, Any],
    corrections: Iterable[tuple[float, float, str]],
) -> list[dict[str, Any]]:
    from focus_ai.vision.correction import _recalculate_result, _row_time, _update_row_state

    timeline = [row for row in analysis_result.get("timeline", []) if isinstance(row, dict)]
    applied = []
    for start, end, state in corrections:
        changed = 0
        previous_states: dict[str, int] = {}
        for row in timeline:
            point = _row_time(row)
            if start <= point < end:
                old_state = str(row.get("state") or "unknown")
                previous_states[old_state] = previous_states.get(old_state, 0) + 1
                if old_state != state:
                    _update_row_state(row, state)
                    row["decision_source"] = "codex_manual_review"
                    changed += 1
        applied.append(
            {
                "start_sec": start,
                "end_sec": end,
                "to_state": state,
                "changed_points": changed,
                "from_states": previous_states,
            }
        )
    if any(item["changed_points"] for item in applied):
        _recalculate_result(analysis_result)
    return applied


def apply_pending(session_id: Any, correction_values: Iterable[str]) -> Path:
    path = pending_path(session_id)
    envelope = _read_json(path)
    if envelope.get("status") != "pending":
        raise RuntimeError(f"review is not pending: {path}")
    analysis_result = envelope.get("analysis_result")
    if not isinstance(analysis_result, dict):
        raise RuntimeError("pending review does not contain analysis_result")
    parsed = [_parse_correction(value) for value in correction_values]
    applied = apply_interval_corrections(analysis_result, parsed)
    review = analysis_result.setdefault("codex_manual_review", {})
    review["status"] = "reviewed"
    review["manual_corrections"] = applied
    review["reviewed_at_unix"] = int(time.time())
    envelope["analysis_result"] = analysis_result
    envelope["reviewed_at_unix"] = int(time.time())
    _write_json(path, envelope)
    return path


def commit_pending(session_id: Any) -> Path:
    path = pending_path(session_id)
    envelope = _read_json(path)
    if envelope.get("status") != "pending":
        raise RuntimeError(f"review is not pending: {path}")
    result = envelope.get("analysis_result")
    job = envelope.get("job")
    sink = str(envelope.get("result_sink") or "rds")
    if not isinstance(result, dict) or not isinstance(job, dict):
        raise RuntimeError("pending review is missing result or job")

    import worker

    # The long-running worker loads .env during startup, but this review CLI is
    # also invoked as a standalone process when Codex approves a pending result.
    # Load the same project environment before opening the configured sink.
    worker._load_env()
    review = result.setdefault("codex_manual_review", {})
    LOGGER.info(
        "corrections approved before commit: session_id=%s, corrections=%s",
        session_id,
        json.dumps(review.get("sdk_corrections") or review.get("manual_corrections") or [], ensure_ascii=False),
    )
    review["status"] = "committed"
    review["committed_at_unix"] = int(time.time())
    worker._validate_and_correct_feedback(result)
    if sink == "rds":
        worker._save_result_to_rds(result)
        verification = verify_rds_result(session_id, worker)
    else:
        backend_url = worker._required_env("BACKEND_RESULT_API_URL")
        worker._post_result(backend_url, worker._build_backend_result_payload(result, job))
        verification = {"sink": "backend_api", "verified": True}

    envelope["status"] = "committed"
    envelope["analysis_result"] = result
    envelope["committed_at_unix"] = int(time.time())
    committed = session_dir(session_id) / "committed_result.json"
    _write_json(committed, envelope)
    path.unlink()
    (session_dir(session_id) / ".sdk_review.lock").unlink(missing_ok=True)
    manifest = _read_json(manifest_path(session_id)) if manifest_path(session_id).exists() else {}
    manifest["status"] = "committed"
    manifest["committed_result_path"] = str(committed.resolve())
    manifest["rds_verification"] = verification
    _write_json(manifest_path(session_id), manifest)
    LOGGER.info(
        "commit complete: session_id=%s, final_focus_score=%s, verification=%s",
        session_id,
        (result.get("summary") or {}).get("focus_score"),
        json.dumps(verification, ensure_ascii=False),
    )
    return committed


def verify_rds_result(session_id: Any, worker_module: Any | None = None) -> dict[str, Any]:
    """Read back all four persisted result areas without changing the RDS schema."""
    if worker_module is None:
        import worker as worker_module

        worker_module._load_env()
    summary_table = worker_module._analysis_result_table()
    feedback_table = worker_module._analysis_feedback_table()
    connection = worker_module._rds_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {summary_table} WHERE session_id = %s", (str(session_id),))
            summary = cursor.fetchone()
            cursor.execute(
                "SELECT t, state FROM analysis_timeline WHERE session_id = %s ORDER BY t, id",
                (str(session_id),),
            )
            timeline = cursor.fetchall()
            cursor.execute(
                "SELECT event_type, start_sec, end_sec, score FROM analysis_events "
                "WHERE session_id = %s ORDER BY start_sec, end_sec, id",
                (str(session_id),),
            )
            events = cursor.fetchall()
            cursor.execute(f"SELECT * FROM {feedback_table} WHERE session_id = %s", (str(session_id),))
            feedback = cursor.fetchone()
    finally:
        connection.close()
    if not summary or not feedback:
        raise RuntimeError(f"RDS read-back failed for session_id={session_id}")
    verification = {
        "sink": "rds",
        "verified": True,
        "summary_found": bool(summary),
        "timeline_rows": len(timeline),
        "event_rows": len(events),
        "feedback_found": bool(feedback),
        "verified_at_unix": int(time.time()),
    }
    LOGGER.info(
        "RDS read-back complete: session_id=%s, summary=%s, timeline_rows=%s, event_rows=%s, feedback=%s",
        session_id,
        bool(summary),
        len(timeline),
        len(events),
        bool(feedback),
    )
    return verification


def inspect_rds_result(session_id: Any) -> dict[str, Any]:
    """Return a JSON-safe RDS/API consistency snapshot for one session."""
    import worker

    worker._load_env()
    summary_table = worker._analysis_result_table()
    feedback_table = worker._analysis_feedback_table()
    connection = worker._rds_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {summary_table} WHERE session_id = %s", (str(session_id),))
            summary = cursor.fetchone() or {}
            cursor.execute(
                "SELECT COUNT(*) AS row_count, MIN(t) AS min_t, MAX(t) AS max_t "
                "FROM analysis_timeline WHERE session_id = %s",
                (str(session_id),),
            )
            timeline = cursor.fetchone() or {}
            cursor.execute(
                "SELECT state, COUNT(*) AS seconds FROM analysis_timeline "
                "WHERE session_id = %s GROUP BY state ORDER BY state",
                (str(session_id),),
            )
            state_rows = cursor.fetchall()
            cursor.execute(
                "SELECT event_type, start_sec, end_sec, score FROM analysis_events "
                "WHERE session_id = %s ORDER BY start_sec, end_sec, id",
                (str(session_id),),
            )
            events = cursor.fetchall()
            cursor.execute(
                f"SELECT feedback_text, feedback_source, feedback_version FROM {feedback_table} "
                "WHERE session_id = %s",
                (str(session_id),),
            )
            feedback = cursor.fetchone() or {}
            cursor.execute("SHOW COLUMNS FROM focus_sessions")
            session_columns = {
                str(row.get("Field")) for row in cursor.fetchall() if isinstance(row, dict) and row.get("Field")
            }
            duration_expression = (
                "duration_sec"
                if "duration_sec" in session_columns
                else "TIMESTAMPDIFF(SECOND, start_time, end_time) AS duration_sec"
            )
            cursor.execute(
                f"SELECT id, user_id, status, start_time, end_time, {duration_expression} "
                "FROM focus_sessions WHERE id = %s",
                (int(session_id),),
            )
            session = cursor.fetchone() or {}
            cursor.execute(
                "SELECT AVG(focus_score) AS avg_focus_score, COUNT(*) AS log_count "
                "FROM focus_logs WHERE session_id = %s",
                (int(session_id),),
            )
            focus_logs = cursor.fetchone() or {}
    finally:
        connection.close()

    focus_ratio = summary.get("focus_ratio")
    derived_score = round(float(focus_ratio) * 100, 1) if _is_finite_number(focus_ratio) else None
    feedback_text = feedback.get("feedback_text")
    return {
        "session_id": int(session_id),
        "summary": {
            "found": bool(summary),
            "focus_ratio": focus_ratio,
            "derived_focus_score": derived_score,
            "absent_count": summary.get("absent_count"),
            "absent_total_sec": summary.get("absent_total_sec"),
            "away_count": summary.get("away_count"),
            "away_total_sec": summary.get("away_total_sec"),
            "bad_posture_ratio": summary.get("bad_posture_ratio"),
        },
        "timeline": {
            "row_count": timeline.get("row_count"),
            "min_t": timeline.get("min_t"),
            "max_t": timeline.get("max_t"),
            "state_seconds": {
                str(row.get("state")): int(row.get("seconds") or 0) for row in state_rows
            },
        },
        "events": events,
        "feedback": {
            "found": bool(feedback),
            "text_length": len(str(feedback_text or "")),
            "source": feedback.get("feedback_source"),
            "version": feedback.get("feedback_version"),
        },
        "session": {
            "found": bool(session),
            "user_id": session.get("user_id"),
            "status": session.get("status"),
            "duration_sec": session.get("duration_sec"),
        },
        "frontend_score_source": {
            "focus_logs_avg": focus_logs.get("avg_focus_score"),
            "focus_log_count": focus_logs.get("log_count"),
        },
    }


def _is_finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in {float("inf"), float("-inf")}


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description="Prepare, correct, and commit Codex-reviewed AI results.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List pending review sessions.")

    apply_parser = subparsers.add_parser("apply", help="Apply manual interval corrections.")
    apply_parser.add_argument("--session-id", required=True)
    apply_parser.add_argument("--correction", action="append", default=[], help="START:END:STATE")
    apply_parser.add_argument("--sdk-result", help="Validated SDK review JSON; defaults to the session review file.")

    review_parser = subparsers.add_parser("review", help="Review one pending session with Codex SDK and local frames.")
    review_parser.add_argument("--session-id", required=True)
    review_parser.add_argument("--max-frames", type=int, default=None)

    subparsers.add_parser("review-worker", help="Continuously review, apply, and commit pending sessions.")

    requeue_parser = subparsers.add_parser(
        "requeue-test",
        help="Safely requeue a committed session for SDK E2E verification.",
    )
    requeue_parser.add_argument("--session-id", required=True)
    requeue_parser.add_argument(
        "--confirm-test-requeue",
        action="store_true",
        help="Required acknowledgement that this creates a marked test pending session.",
    )

    inspect_parser = subparsers.add_parser("inspect-rds", help="Inspect persisted RDS and UI score sources.")
    inspect_parser.add_argument("--session-id", required=True)

    commit_parser = subparsers.add_parser("commit", help="Commit a reviewed result to its configured sink.")
    commit_parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    if args.command == "list":
        print(json.dumps(list_pending(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply":
        if args.correction:
            path = apply_pending(args.session_id, args.correction)
            print(path)
        else:
            from codex_sdk_review import apply_review_decision

            print(json.dumps(apply_review_decision(args.session_id, args.sdk_result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review":
        from codex_sdk_review import review_session

        reviewed = review_session(args.session_id, args.max_frames)
        decision = reviewed["decision"]
        metadata = reviewed["metadata"]
        print(
            json.dumps(
                {
                    "session_id": decision.get("session_id"),
                    "final_score": decision.get("final_focus_score"),
                    "corrections": decision.get("corrections"),
                    "status": reviewed["validation"].get("effective_status"),
                    "note": f"frames={metadata.get('frame_count')}, thread_id={metadata.get('thread_id')}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "review-worker":
        from codex_sdk_review import run_review_worker

        run_review_worker()
        return 0
    if args.command == "requeue-test":
        if not args.confirm_test_requeue:
            parser.error("requeue-test requires --confirm-test-requeue")
        print(create_test_pending_from_committed(args.session_id))
        return 0
    if args.command == "inspect-rds":
        print(json.dumps(inspect_rds_result(args.session_id), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "commit":
        path = commit_pending(args.session_id)
        print(path)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
