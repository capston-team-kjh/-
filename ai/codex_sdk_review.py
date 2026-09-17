from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

import codex_review


LOGGER = logging.getLogger("focusai.codex_review")
SCHEMA_VERSION = "focusai-codex-frame-review-v1"
DEFAULT_MAX_CORRECTION_SEC = 15.0
REVIEW_RESULT_NAME = "sdk_review_result.json"
REVIEW_METADATA_NAME = "sdk_review_metadata.json"
RAW_RESPONSE_NAME = "sdk_review_raw.txt"
BRIDGE_PATH = codex_review.AI_DIR / "codex_frame_review.mjs"

REVIEW_STATUSES = {"no_change", "corrected", "needs_manual_check", "error"}
CONFIDENCES = {"high", "medium", "low"}
CORRECTION_KEYS = {
    "start_sec",
    "end_sec",
    "original_state",
    "corrected_state",
    "reason",
    "confidence",
    "evidence_frames",
}
RESULT_KEYS = {
    "session_id",
    "review_status",
    "final_focus_score",
    "corrections",
    "summary_reason",
}


class ReviewError(RuntimeError):
    pass


class ReviewValidationError(ReviewError):
    pass


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _session_number(value: Any) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ReviewValidationError(f"SDK review requires a numeric session_id, got {value!r}") from exc
    if number < 0:
        raise ReviewValidationError(f"session_id must be non-negative, got {number}")
    return number


def _read_context(session_id: Any) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    directory = codex_review.review_root() / f"session_{codex_review._safe_name(session_id)}"
    pending = directory / "pending_result.json"
    manifest_file = directory / "review_manifest.json"
    if not pending.exists():
        raise ReviewError(f"pending_result.json is missing: {pending}")
    if not manifest_file.exists():
        raise ReviewError(f"review_manifest.json is missing: {manifest_file}")
    envelope = codex_review._read_json(pending)
    manifest = codex_review._read_json(manifest_file)
    if envelope.get("status") != "pending":
        raise ReviewError(f"session is not pending: {session_id}")
    analysis_result = envelope.get("analysis_result")
    if not isinstance(analysis_result, dict):
        raise ReviewError("pending_result.json does not contain analysis_result")
    if str(envelope.get("session_id")) != str(manifest.get("session_id")):
        raise ReviewError("session_id differs between pending_result.json and review_manifest.json")
    return directory, envelope, manifest, analysis_result


def _row_time(row: dict[str, Any]) -> float | None:
    for key in ("t", "time", "time_sec", "timestamp_sec"):
        value = row.get(key)
        if _is_number(value):
            return float(value)
    return None


def _timeline_bounds(analysis_result: dict[str, Any]) -> tuple[float, float]:
    timeline = analysis_result.get("timeline")
    points = sorted(
        point
        for row in timeline if isinstance(row, dict)
        if (point := _row_time(row)) is not None
    ) if isinstance(timeline, list) else []
    if not points:
        raise ReviewValidationError("analysis timeline is empty")

    positive_steps = [b - a for a, b in zip(points, points[1:]) if b > a]
    step = statistics.median(positive_steps) if positive_steps else 1.0
    timeline_end = points[-1] + max(0.001, step)
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    meta = analysis_result.get("meta") if isinstance(analysis_result.get("meta"), dict) else {}
    duration_candidates = [
        meta.get("duration_sec"),
        meta.get("video_duration_sec"),
        summary.get("total_time_sec"),
        summary.get("total_seconds"),
    ]
    durations = [float(value) for value in duration_candidates if _is_number(value) and float(value) > 0]
    upper = min([timeline_end, *durations]) if durations else timeline_end
    if upper <= points[0]:
        raise ReviewValidationError("analysis duration does not overlap its timeline")
    return max(0.0, points[0]), upper


def review_output_schema(session_id: Any, analysis_result: dict[str, Any]) -> dict[str, Any]:
    session_number = _session_number(session_id)
    lower, upper = _timeline_bounds(analysis_result)
    states = sorted(codex_review.VALID_STATES)
    return {
        "type": "object",
        "properties": {
            "session_id": {"type": "integer", "const": session_number},
            "review_status": {"type": "string", "enum": sorted(REVIEW_STATUSES)},
            "final_focus_score": {
                "anyOf": [
                    {"type": "number", "minimum": 0, "maximum": 100},
                    {"type": "null"},
                ]
            },
            "corrections": {
                "type": "array",
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "properties": {
                        "start_sec": {"type": "number", "minimum": lower, "maximum": upper},
                        "end_sec": {"type": "number", "minimum": lower, "maximum": upper},
                        "original_state": {"type": "string", "enum": states},
                        "corrected_state": {"type": "string", "enum": states},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "confidence": {"type": "string", "enum": sorted(CONFIDENCES)},
                        "evidence_frames": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 20,
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                    "required": sorted(CORRECTION_KEYS),
                    "additionalProperties": False,
                },
            },
            "summary_reason": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
        "required": sorted(RESULT_KEYS),
        "additionalProperties": False,
    }


def _resolve_manifest_frame(directory: Path, raw_path: Any, by_name: dict[str, Path]) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    supplied = Path(raw_path)
    candidates = [supplied] if supplied.is_absolute() else [directory / supplied]
    fallback = by_name.get(supplied.name.lower())
    if fallback is not None:
        candidates.append(fallback)
    root = directory.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.is_file() and resolved.suffix.lower() in {".jpg", ".jpeg"}:
            return resolved
    return None


def _filename_time(path: Path) -> float | None:
    match = re.search(r"_(\d+(?:\.\d+)?)s$", path.stem)
    return float(match.group(1)) if match else None


def _manifest_frames(directory: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    disk_frames = sorted(directory.glob("chunk_*/frames/*.jpg"))
    by_name = {path.name.lower(): path.resolve() for path in disk_frames}
    review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    chunks = review.get("chunks") if isinstance(review.get("chunks"), list) else manifest.get("chunks")
    chunks = chunks if isinstance(chunks, list) else []
    rows: list[dict[str, Any]] = []
    missing = 0
    seen: set[Path] = set()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_index = chunk.get("chunk_index")
        offset = float(chunk.get("offset_sec")) if _is_number(chunk.get("offset_sec")) else 0.0
        frames = chunk.get("frames") if isinstance(chunk.get("frames"), list) else []
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            path = _resolve_manifest_frame(directory, frame.get("path"), by_name)
            if path is None:
                missing += 1
                continue
            if path in seen:
                continue
            seen.add(path)
            local_time = float(frame.get("time_sec")) if _is_number(frame.get("time_sec")) else _filename_time(path)
            global_time = (
                float(frame.get("global_time_sec"))
                if _is_number(frame.get("global_time_sec"))
                else (offset + local_time if local_time is not None else None)
            )
            rows.append(
                {
                    "path": str(path),
                    "label": path.relative_to(directory.resolve()).as_posix(),
                    "chunk_index": chunk_index,
                    "time_sec": local_time,
                    "global_time_sec": global_time,
                    "original_state": str(frame.get("original_state") or "unknown"),
                }
            )

    for path in disk_frames:
        resolved = path.resolve()
        if resolved in seen:
            continue
        rows.append(
            {
                "path": str(resolved),
                "label": resolved.relative_to(directory.resolve()).as_posix(),
                "chunk_index": path.parent.parent.name.removeprefix("chunk_"),
                "time_sec": _filename_time(path),
                "global_time_sec": _filename_time(path),
                "original_state": "unknown",
            }
        )
    return rows, missing


def _event_details(analysis_result: dict[str, Any]) -> list[tuple[float, float, str]]:
    details = []
    events = analysis_result.get("events")
    if not isinstance(events, list):
        return details
    for event in events:
        if not isinstance(event, dict):
            continue
        start = event.get("start_sec", event.get("start_time"))
        end = event.get("end_sec", event.get("end_time"))
        state = str(event.get("type") or event.get("event_type") or event.get("state") or "unknown")
        if _is_number(start) and _is_number(end) and state in codex_review.VALID_STATES - {"focus"}:
            details.append((float(start), float(end), state))
    return details


def _even_sample(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not rows:
        return []
    ordered = sorted(rows, key=lambda row: float(row.get("global_time_sec") or 0))
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    indexes = {round(index * (len(ordered) - 1) / (count - 1)) for index in range(count)}
    return [ordered[index] for index in sorted(indexes)]


def select_representative_frames(
    directory: Path,
    manifest: dict[str, Any],
    analysis_result: dict[str, Any],
    max_frames: int,
) -> tuple[list[dict[str, Any]], int]:
    if max_frames < 1:
        raise ReviewValidationError("max_frames must be at least 1")
    frames, missing = _manifest_frames(directory, manifest)
    if not frames:
        raise ReviewError(f"no review frame exists under {directory}")
    if len(frames) <= max_frames:
        return sorted(frames, key=lambda row: float(row.get("global_time_sec") or 0)), missing

    events = _event_details(analysis_result)
    normal = [row for row in frames if row.get("original_state") == "focus"]
    comparison_count = min(len(normal), max(2, max_frames // 5)) if max_frames >= 4 else min(len(normal), 1)
    selected_normal = _even_sample(normal, comparison_count)
    selected_labels = {row["label"] for row in selected_normal}

    def priority(row: dict[str, Any]) -> tuple[float, float]:
        point = float(row.get("global_time_sec") or 0)
        state = str(row.get("original_state") or "unknown")
        score = 40.0 if state != "focus" else 0.0
        for start, end, event_state in events:
            if start - 1.0 <= point <= end + 1.0:
                score += 100.0
                if start <= point <= end:
                    score += 50.0
                score += max(0.0, 20.0 - 10.0 * min(abs(point - start), abs(point - end)))
                if state == event_state:
                    score += 20.0
        return score, -point

    candidates = sorted(
        (row for row in frames if row["label"] not in selected_labels),
        key=priority,
        reverse=True,
    )
    chosen = candidates[: max_frames - len(selected_normal)] + selected_normal
    return sorted(chosen, key=lambda row: float(row.get("global_time_sec") or 0)), missing


def _prompt_payload(session_id: Any, analysis_result: dict[str, Any], frames: list[dict[str, Any]]) -> str:
    summary = analysis_result.get("summary") if isinstance(analysis_result.get("summary"), dict) else {}
    payload = {
        "session_id": _session_number(session_id),
        "focus_score": summary.get("focus_score", analysis_result.get("focus_score")),
        "summary": summary,
        "timeline": analysis_result.get("timeline") if isinstance(analysis_result.get("timeline"), list) else [],
        "events": analysis_result.get("events") if isinstance(analysis_result.get("events"), list) else [],
        "feedback": analysis_result.get("feedback") if isinstance(analysis_result.get("feedback"), dict) else {},
        "personal_feedback": (
            analysis_result.get("personal_feedback")
            if isinstance(analysis_result.get("personal_feedback"), dict)
            else {}
        ),
        "frames": [
            {
                "label": frame["label"],
                "chunk_index": frame.get("chunk_index"),
                "time_sec": frame.get("time_sec"),
                "global_time_sec": frame.get("global_time_sec"),
                "original_state": frame.get("original_state"),
            }
            for frame in frames
        ],
    }
    rules = """
You are the second-pass visual reviewer for FocusAI. Compare the existing analysis JSON with only the attached extracted JPG frames. Never request or inspect a video. Preserve the existing result unless a frame-backed false positive is obvious.

Return only the JSON object required by the supplied output schema. Use only these project states: focus, absent, drowsy, sleep_suspect, gaze_side, gaze_down, bad_posture, unknown. Put exact frame labels from the payload in evidence_frames.

Correction policy:
- Use confidence=high only when the attached frames make the correction visually unambiguous. Medium/low means needs_manual_check and must not be presented as an automatic correction.
- Keep uncertain intervals unchanged. Correct only the narrow interval directly supported by evidence.
- absent requires the person to be clearly missing, with no face/body/desk-presence evidence. A lowered head, partial body, or overhead face-detection failure is not absence.
- drowsy requires clear closed eyes, head drop, or sustained eye closure evidence.
- gaze_side/gaze_down require a clear side/down/out-of-task gaze. Do not infer gaze direction from face-detector failure.
- bad_posture requires clear head-down, leaning, or sustained abnormal posture evidence.
- start_sec must be less than end_sec and remain inside the supplied timeline/video duration.
- final_focus_score is advisory only; use null when the available frames cannot support recomputing the full score.
""".strip()
    return f"{rules}\n\nExisting analysis and frame index:\n{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"


def _bridge_timeout() -> float:
    raw = os.getenv("CODEX_REVIEW_TIMEOUT_SEC", "900")
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 900.0


def _run_sdk_bridge(request: dict[str, Any]) -> dict[str, Any]:
    if not BRIDGE_PATH.exists():
        raise ReviewError(f"Codex SDK bridge is missing: {BRIDGE_PATH}")
    try:
        completed = subprocess.run(
            ["node", str(BRIDGE_PATH)],
            cwd=codex_review.PROJECT_ROOT,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=_bridge_timeout(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewError(f"Codex SDK process failed to start or timed out: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise ReviewError(f"Codex SDK failed: {detail}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"Codex SDK bridge returned invalid JSON: {exc}") from exc
    if not isinstance(response, dict):
        raise ReviewError("Codex SDK bridge response must be an object")
    return response


def _parse_final_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise ReviewValidationError("Codex SDK returned an empty final response")
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewValidationError(f"Codex SDK response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ReviewValidationError("Codex SDK correction response must be an object")
    return parsed


def _states_in_interval(analysis_result: dict[str, Any], start: float, end: float) -> set[str]:
    states = set()
    timeline = analysis_result.get("timeline")
    if not isinstance(timeline, list):
        return states
    for row in timeline:
        if not isinstance(row, dict):
            continue
        point = _row_time(row)
        if point is not None and start <= point < end:
            states.add(str(row.get("state") or "unknown"))
    return states


def _max_correction_sec() -> float:
    raw = os.getenv("CODEX_REVIEW_MAX_CORRECTION_SEC", str(DEFAULT_MAX_CORRECTION_SEC))
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_MAX_CORRECTION_SEC


def validate_review_result(
    decision: dict[str, Any],
    session_id: Any,
    analysis_result: dict[str, Any],
    selected_frames: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    schema_errors: list[str] = []
    semantic_errors: list[str] = []
    if set(decision) != RESULT_KEYS:
        schema_errors.append(f"top-level keys must be exactly {sorted(RESULT_KEYS)}")
    if decision.get("session_id") != _session_number(session_id):
        schema_errors.append("session_id does not match the pending session")
    status = decision.get("review_status")
    if status not in REVIEW_STATUSES:
        schema_errors.append(f"review_status must be one of {sorted(REVIEW_STATUSES)}")
    final_score = decision.get("final_focus_score")
    if final_score is not None and (not _is_number(final_score) or not 0 <= float(final_score) <= 100):
        schema_errors.append("final_focus_score must be null or a number from 0 to 100")
    if not isinstance(decision.get("summary_reason"), str) or not decision.get("summary_reason", "").strip():
        schema_errors.append("summary_reason must be a non-empty string")
    corrections = decision.get("corrections")
    if not isinstance(corrections, list):
        schema_errors.append("corrections must be an array")
        corrections = []

    lower, upper = _timeline_bounds(analysis_result)
    frame_map = {
        str(frame.get("label")): frame
        for frame in selected_frames
        if isinstance(frame, dict) and frame.get("label")
    }
    auto: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for index, correction in enumerate(corrections):
        prefix = f"corrections[{index}]"
        errors: list[str] = []
        if not isinstance(correction, dict):
            schema_errors.append(f"{prefix} must be an object")
            continue
        if set(correction) != CORRECTION_KEYS:
            schema_errors.append(f"{prefix} keys must be exactly {sorted(CORRECTION_KEYS)}")
            continue
        start = correction.get("start_sec")
        end = correction.get("end_sec")
        if not _is_number(start) or not _is_number(end):
            errors.append("start_sec and end_sec must be finite numbers")
        else:
            start = float(start)
            end = float(end)
            if not start < end:
                errors.append("start_sec must be less than end_sec")
            if start < lower or end > upper + 1e-6:
                errors.append(f"interval must stay inside {lower:.3f}..{upper:.3f} sec")
            if end - start > _max_correction_sec():
                errors.append(f"interval exceeds automatic limit {_max_correction_sec():.3f} sec")
        original_state = correction.get("original_state")
        corrected_state = correction.get("corrected_state")
        if original_state not in codex_review.VALID_STATES:
            errors.append("original_state is not a project state")
        if corrected_state not in codex_review.VALID_STATES:
            errors.append("corrected_state is not a project state")
        if original_state == corrected_state:
            errors.append("corrected_state must differ from original_state")
        if correction.get("confidence") not in CONFIDENCES:
            errors.append("confidence must be high, medium, or low")
        if not isinstance(correction.get("reason"), str) or not correction.get("reason", "").strip():
            errors.append("reason must be a non-empty string")
        evidence = correction.get("evidence_frames")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) for item in evidence):
            errors.append("evidence_frames must contain frame labels")
            evidence = []
        unknown_evidence = [label for label in evidence if label not in frame_map]
        if unknown_evidence:
            errors.append(f"unknown evidence frame(s): {unknown_evidence}")
        if _is_number(start) and _is_number(end):
            evidence_times = [
                frame_map[label].get("global_time_sec")
                for label in evidence
                if label in frame_map and _is_number(frame_map[label].get("global_time_sec"))
            ]
            if not any(float(start) - 1.0 <= float(point) <= float(end) + 1.0 for point in evidence_times):
                errors.append("no evidence frame is within one second of the correction interval")
            if original_state in codex_review.VALID_STATES:
                interval_states = _states_in_interval(analysis_result, float(start), float(end))
                if original_state not in interval_states:
                    errors.append(f"original_state {original_state!r} is not present in the interval")

        normalized = dict(correction)
        if errors:
            semantic_errors.extend(f"{prefix}: {error}" for error in errors)
            manual.append(normalized)
        elif correction.get("confidence") == "high":
            auto.append(normalized)
        else:
            manual.append(normalized)

    if status == "no_change" and corrections:
        semantic_errors.append("no_change response must have an empty corrections array")
    if status == "corrected" and not corrections:
        semantic_errors.append("corrected response must contain at least one correction")
    if status == "error":
        effective_status = "error"
    elif schema_errors:
        effective_status = "error"
    elif status == "needs_manual_check" or manual or semantic_errors:
        effective_status = "needs_manual_check"
    elif status == "corrected" and auto:
        effective_status = "corrected"
    elif status == "no_change":
        effective_status = "no_change"
    else:
        effective_status = "needs_manual_check"
    return {
        "effective_status": effective_status,
        "auto_corrections": auto,
        "manual_corrections": manual,
        "schema_errors": schema_errors,
        "semantic_errors": semantic_errors,
    }


def _update_manifest(session_id: Any, **values: Any) -> dict[str, Any]:
    path = codex_review.manifest_path(session_id)
    manifest = codex_review._read_json(path) if path.exists() else {"session_id": session_id}
    sdk = manifest.get("sdk_review") if isinstance(manifest.get("sdk_review"), dict) else {}
    sdk.update(values)
    manifest["sdk_review"] = sdk
    if values.get("thread_id"):
        manifest["thread_id"] = values["thread_id"]
    codex_review._write_json(path, manifest)
    return manifest


def review_session(session_id: Any, max_frames: int | None = None) -> dict[str, Any]:
    started = time.time()
    directory, _envelope, manifest, analysis_result = _read_context(session_id)
    frame_limit = max_frames if max_frames is not None else codex_review._review_frame_count()
    LOGGER.info("Codex SDK review started: session_id=%s", session_id)
    frames, missing = select_representative_frames(directory, manifest, analysis_result, frame_limit)
    if missing:
        LOGGER.warning("review manifest referenced missing frames: session_id=%s, missing=%s", session_id, missing)
    thread_id = manifest.get("thread_id")
    if not thread_id:
        sdk_meta = manifest.get("sdk_review") if isinstance(manifest.get("sdk_review"), dict) else {}
        thread_id = sdk_meta.get("thread_id")
    request = {
        "working_directory": str(codex_review.PROJECT_ROOT.resolve()),
        "thread_id": thread_id,
        "model": os.getenv("CODEX_REVIEW_MODEL") or None,
        "model_reasoning_effort": os.getenv("CODEX_REVIEW_REASONING_EFFORT") or None,
        "prompt": _prompt_payload(session_id, analysis_result, frames),
        "image_paths": [frame["path"] for frame in frames],
        "output_schema": review_output_schema(session_id, analysis_result),
    }
    response = _run_sdk_bridge(request)
    returned_thread_id = response.get("thread_id")
    if not isinstance(returned_thread_id, str) or not returned_thread_id.strip():
        raise ReviewError("Codex SDK did not return a thread_id")
    _update_manifest(
        session_id,
        status="response_received",
        thread_id=returned_thread_id,
        frame_count=len(frames),
        missing_frame_count=missing,
        reviewed_at_unix=int(time.time()),
    )
    raw_response = response.get("final_response")
    try:
        decision = _parse_final_response(raw_response)
    except ReviewValidationError:
        (directory / RAW_RESPONSE_NAME).write_text(str(raw_response or ""), encoding="utf-8")
        _update_manifest(session_id, status="error", error="SDK response JSON parsing failed")
        raise
    codex_review._write_json(directory / REVIEW_RESULT_NAME, decision)
    validation = validate_review_result(decision, session_id, analysis_result, frames)
    if missing:
        validation["effective_status"] = "needs_manual_check"
        validation["semantic_errors"].append(
            f"review manifest references {missing} missing frame file(s); automatic commit is disabled"
        )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "session_id": _session_number(session_id),
        "thread_id": returned_thread_id,
        "frame_count": len(frames),
        "missing_frame_count": missing,
        "selected_frames": frames,
        "validation": validation,
        "usage": response.get("usage"),
        "reviewed_at_unix": int(time.time()),
    }
    codex_review._write_json(directory / REVIEW_METADATA_NAME, metadata)
    _update_manifest(
        session_id,
        status=validation["effective_status"],
        result_path=str((directory / REVIEW_RESULT_NAME).resolve()),
        metadata_path=str((directory / REVIEW_METADATA_NAME).resolve()),
        schema_errors=validation["schema_errors"],
        semantic_errors=validation["semantic_errors"],
    )
    LOGGER.info(
        "Codex SDK review finished: session_id=%s, frames=%s, thread_id=%s, status=%s, elapsed_sec=%.1f",
        session_id,
        len(frames),
        returned_thread_id,
        validation["effective_status"],
        time.time() - started,
    )
    return {"decision": decision, "metadata": metadata, "validation": validation}


def apply_review_decision(session_id: Any, review_file: str | Path | None = None) -> dict[str, Any]:
    directory, envelope, _manifest, analysis_result = _read_context(session_id)
    decision_path = Path(review_file).resolve() if review_file else directory / REVIEW_RESULT_NAME
    if not decision_path.exists():
        raise ReviewError(f"SDK review result is missing: {decision_path}")
    decision = codex_review._read_json(decision_path)
    metadata_path = directory / REVIEW_METADATA_NAME
    if not metadata_path.exists():
        raise ReviewError(f"SDK review metadata is missing: {metadata_path}")
    metadata = codex_review._read_json(metadata_path)
    selected_frames = metadata.get("selected_frames")
    if not isinstance(selected_frames, list):
        raise ReviewError("SDK review metadata does not contain selected_frames")
    validation = validate_review_result(decision, session_id, analysis_result, selected_frames)
    if int(metadata.get("missing_frame_count") or 0) > 0:
        validation["effective_status"] = "needs_manual_check"
        validation["semantic_errors"].append(
            "automatic commit is disabled because one or more manifest frames are missing"
        )
    if validation["schema_errors"]:
        raise ReviewValidationError("; ".join(validation["schema_errors"]))

    correction_values = [
        (float(item["start_sec"]), float(item["end_sec"]), str(item["corrected_state"]))
        for item in validation["auto_corrections"]
    ]
    LOGGER.info(
        "automatic correction candidates before RDS commit: session_id=%s, corrections=%s",
        session_id,
        json.dumps(validation["auto_corrections"], ensure_ascii=False),
    )
    applied = codex_review.apply_interval_corrections(analysis_result, correction_values)
    review = analysis_result.setdefault("codex_manual_review", {})
    review["status"] = (
        "reviewed"
        if validation["effective_status"] in {"no_change", "corrected"}
        else "needs_manual_check"
    )
    review["sdk_thread_id"] = metadata.get("thread_id")
    review["sdk_review_status"] = validation["effective_status"]
    review["sdk_corrections"] = validation["auto_corrections"]
    review["manual_check_corrections"] = validation["manual_corrections"]
    review["manual_corrections"] = applied
    review["reviewed_at_unix"] = int(time.time())
    envelope["analysis_result"] = analysis_result
    envelope["reviewed_at_unix"] = int(time.time())
    codex_review._write_json(codex_review.pending_path(session_id), envelope)
    final_score = (analysis_result.get("summary") or {}).get("focus_score")
    _update_manifest(
        session_id,
        status=validation["effective_status"],
        apply_success=True,
        applied_corrections=applied,
        final_focus_score=final_score,
    )
    LOGGER.info(
        "SDK corrections applied: session_id=%s, corrections=%s, final_focus_score=%s, apply_success=true",
        session_id,
        json.dumps(applied, ensure_ascii=False),
        final_score,
    )
    return {
        "session_id": _session_number(session_id),
        "status": validation["effective_status"],
        "final_score": final_score,
        "corrections": applied,
        "manual_corrections": validation["manual_corrections"],
        "path": str(codex_review.pending_path(session_id)),
    }


def _report(result: dict[str, Any]) -> None:
    LOGGER.info(
        "session_id: %s\nfinal_score: %s\ncorrections: %s\nstatus: %s\nnote: %s",
        result.get("session_id"),
        result.get("final_score"),
        json.dumps(result.get("corrections", []), ensure_ascii=False),
        result.get("status"),
        result.get("note", ""),
    )


def process_pending_session(session_id: Any, auto_commit: bool = True) -> dict[str, Any]:
    reviewed = review_session(session_id)
    applied = apply_review_decision(session_id)
    validation = reviewed["validation"]
    can_commit = (
        auto_commit
        and validation["effective_status"] in {"no_change", "corrected"}
        and not validation["manual_corrections"]
        and not validation["semantic_errors"]
    )
    committed_path = None
    if can_commit:
        committed_path = codex_review.commit_pending(session_id)
        _update_manifest(session_id, status="committed", commit_success=True)
        status = "committed"
        note = f"RDS commit complete: {committed_path}"
    else:
        status = validation["effective_status"]
        _update_manifest(session_id, status=status, commit_success=False)
        note = "kept pending for manual confirmation" if status == "needs_manual_check" else "commit skipped"
    result = {
        **applied,
        "status": status,
        "note": note,
        "committed_path": str(committed_path) if committed_path else None,
    }
    _report(result)
    return result


def _poll_interval() -> float:
    try:
        return max(1.0, float(os.getenv("CODEX_REVIEW_POLL_SEC", "5")))
    except ValueError:
        return 5.0


def _retry_interval() -> float:
    try:
        return max(30.0, float(os.getenv("CODEX_REVIEW_ERROR_RETRY_SEC", "300")))
    except ValueError:
        return 300.0


def run_review_worker(stop_event: Any = None) -> None:
    while stop_event is None or not stop_event.is_set():
        for item in codex_review.list_pending():
            session_id = item.get("session_id")
            directory = codex_review.session_dir(session_id)
            manifest_file = codex_review.manifest_path(session_id)
            try:
                manifest = codex_review._read_json(manifest_file) if manifest_file.exists() else {}
                sdk = manifest.get("sdk_review") if isinstance(manifest.get("sdk_review"), dict) else {}
                if sdk.get("status") == "needs_manual_check":
                    continue
                last_error = sdk.get("error_at_unix")
                if sdk.get("status") == "error" and _is_number(last_error):
                    if time.time() - float(last_error) < _retry_interval():
                        continue
                lock_path = directory / ".sdk_review.lock"
                try:
                    lock = lock_path.open("x", encoding="utf-8")
                except FileExistsError:
                    continue
                try:
                    lock.write(f"pid={os.getpid()} time={int(time.time())}\n")
                    lock.close()
                    process_pending_session(session_id, auto_commit=True)
                finally:
                    if not lock.closed:
                        lock.close()
                    lock_path.unlink(missing_ok=True)
            except Exception as exc:
                LOGGER.exception("Codex SDK review failed: session_id=%s", session_id)
                try:
                    _update_manifest(
                        session_id,
                        status="error",
                        error=str(exc),
                        error_summary=f"{type(exc).__name__}: {exc}",
                        traceback=traceback.format_exc(),
                        error_at_unix=int(time.time()),
                        apply_success=False,
                        commit_success=False,
                    )
                except Exception:
                    LOGGER.exception("could not persist Codex SDK review error: session_id=%s", session_id)
                _report(
                    {
                        "session_id": session_id,
                        "final_score": None,
                        "corrections": [],
                        "status": "error",
                        "note": f"{type(exc).__name__}: {exc}",
                    }
                )
        if stop_event is not None:
            stop_event.wait(_poll_interval())
        else:
            time.sleep(_poll_interval())
