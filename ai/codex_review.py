from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable


AI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AI_DIR.parent
DEFAULT_REVIEW_DIR = "ai/manual_review_queue"
DEFAULT_REVIEW_FRAMES = 20
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
            items.append(
                {
                    "session_id": envelope.get("session_id"),
                    "user_id": envelope.get("user_id"),
                    "path": str(path.resolve()),
                    "queued_at_unix": envelope.get("queued_at_unix"),
                }
            )
    return items


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
    review["status"] = "committed"
    review["committed_at_unix"] = int(time.time())
    worker._validate_and_correct_feedback(result)
    if sink == "rds":
        worker._save_result_to_rds(result)
    else:
        backend_url = worker._required_env("BACKEND_RESULT_API_URL")
        worker._post_result(backend_url, worker._build_backend_result_payload(result, job))

    envelope["status"] = "committed"
    envelope["analysis_result"] = result
    envelope["committed_at_unix"] = int(time.time())
    committed = session_dir(session_id) / "committed_result.json"
    _write_json(committed, envelope)
    path.unlink()
    manifest = _read_json(manifest_path(session_id)) if manifest_path(session_id).exists() else {}
    manifest["status"] = "committed"
    manifest["committed_result_path"] = str(committed.resolve())
    _write_json(manifest_path(session_id), manifest)
    return committed


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare, correct, and commit Codex-reviewed AI results.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List pending review sessions.")

    apply_parser = subparsers.add_parser("apply", help="Apply manual interval corrections.")
    apply_parser.add_argument("--session-id", required=True)
    apply_parser.add_argument("--correction", action="append", default=[], help="START:END:STATE")

    commit_parser = subparsers.add_parser("commit", help="Commit a reviewed result to its configured sink.")
    commit_parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    if args.command == "list":
        print(json.dumps(list_pending(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply":
        path = apply_pending(args.session_id, args.correction)
        print(path)
        return 0
    if args.command == "commit":
        path = commit_pending(args.session_id)
        print(path)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
