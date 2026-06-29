from __future__ import annotations

from typing import Any


PRIMARY_STATES = {
    "focus",
    "absent",
    "drowsy",
    "sleep_suspect",
    "gaze_away",
    "gaze_side",
    "gaze_down",
    "bad_posture",
    "unknown",
    "present_unknown",
}

VISION_TO_RULE_STATE = {
    "present_normal": "focus",
    "present_head_down": "bad_posture",
    "present_occluded": "unknown",
    "present_side_view": "gaze_side",
    "absent": "absent",
    "drowsy_possible": "drowsy",
    "gaze_away_possible": "gaze_side",
    "bad_posture_possible": "bad_posture",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _row_time(row: dict[str, Any]) -> float:
    return _number(row.get("t", row.get("time", 0.0)))


def _find_timeline_row(timeline: list[dict[str, Any]], time_sec: float) -> dict[str, Any] | None:
    if not timeline:
        return None
    row = min(timeline, key=lambda item: abs(_row_time(item) - time_sec))
    return row if abs(_row_time(row) - time_sec) <= 1.0 else None


def _update_row_state(row: dict[str, Any], new_state: str) -> None:
    old_state = str(row.get("state") or "unknown")
    row["vision_original_state"] = old_state
    row["state"] = new_state
    row["decision_source"] = "openai_vision_correction"

    states = row.get("states") if isinstance(row.get("states"), list) else []
    secondary = [str(state) for state in states if str(state) not in PRIMARY_STATES]
    row["states"] = list(dict.fromkeys([new_state, *secondary]))

    flags = row.get("flags")
    if isinstance(flags, dict):
        for flag in ("absent", "drowsy", "gaze_side", "gaze_down", "bad_posture", "unknown"):
            flags[flag] = new_state == flag
        if new_state == "focus":
            flags["face_seen"] = True
        row["flags"] = flags


def _count_segments(states: list[str], target: str) -> tuple[int, int]:
    count = 0
    total = 0
    active = False
    for state in states:
        matched = state == target
        total += int(matched)
        if matched and not active:
            count += 1
        active = matched
    return count, total


def _primary_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: str | None = None
    start = 0.0
    last = 0.0
    for row in sorted(timeline, key=_row_time):
        point = _row_time(row)
        state = str(row.get("state") or "unknown")
        event_state = None if state == "focus" else state
        if event_state != current:
            if current is not None:
                events.append(
                    {"type": current, "start_sec": start, "end_sec": point, "source": "vision_corrected"}
                )
            current = event_state
            start = point
        last = point
    if current is not None:
        events.append(
            {"type": current, "start_sec": start, "end_sec": last + 1.0, "source": "vision_corrected"}
        )
    return events


def _recalculate_result(analysis_result: dict[str, Any]) -> None:
    timeline = [row for row in analysis_result.get("timeline", []) if isinstance(row, dict)]
    if not timeline:
        return
    timeline.sort(key=_row_time)
    states = [str(row.get("state") or "unknown") for row in timeline]
    summary = analysis_result.get("summary")
    if not isinstance(summary, dict):
        summary = {}

    for state in ("absent", "drowsy", "gaze_side", "gaze_down", "bad_posture", "unknown"):
        count, total = _count_segments(states, state)
        summary[f"{state}_count"] = count
        summary[f"{state}_total_sec"] = total

    focus_total = sum(state == "focus" for state in states)
    total_time = len(states)
    absent_total = int(summary.get("absent_total_sec", 0))
    summary["focus_total_sec"] = focus_total
    summary["focus_time_sec"] = focus_total
    summary["present_total_sec"] = max(0, total_time - absent_total)
    summary["away_count"] = int(summary.get("gaze_side_count", 0))
    summary["away_total_sec"] = int(summary.get("gaze_side_total_sec", 0))
    summary["gaze_away_count"] = int(summary.get("gaze_side_count", 0)) + int(
        summary.get("gaze_down_count", 0)
    )
    summary["gaze_away_total_sec"] = int(summary.get("gaze_side_total_sec", 0)) + int(
        summary.get("gaze_down_total_sec", 0)
    )
    summary["focus_ratio"] = round(focus_total / total_time, 4) if total_time else 0.0
    summary["bad_posture_ratio"] = (
        round(int(summary.get("bad_posture_total_sec", 0)) / total_time, 4) if total_time else 0.0
    )

    try:
        from analyzer.focus_score import calculate_focus_score
    except ImportError:
        from ai.analyzer.focus_score import calculate_focus_score

    summary.update(calculate_focus_score(summary, total_time))
    summary["concentration_score"] = float(summary.get("focus_score", 0))
    analysis_result["summary"] = summary

    existing_events = analysis_result.get("events")
    preserved = []
    if isinstance(existing_events, list):
        preserved = [
            event
            for event in existing_events
            if isinstance(event, dict) and str(event.get("type")) not in PRIMARY_STATES
        ]
    analysis_result["events"] = sorted(
        [*_primary_events(timeline), *preserved],
        key=lambda event: (_number(event.get("start_sec")), _number(event.get("end_sec"))),
    )


def apply_vision_corrections(
    analysis_result: dict[str, Any],
    vision_result: dict[str, Any],
    *,
    minimum_confidence: float = 0.75,
) -> dict[str, Any]:
    timeline = [row for row in analysis_result.get("timeline", []) if isinstance(row, dict)]
    corrections = vision_result.get("corrections")
    if not timeline or not isinstance(corrections, list):
        return {"applied_count": 0, "skipped_count": 0}

    overall_confidence = _number(vision_result.get("confidence"), 0.0)
    score_before = _number(
        (analysis_result.get("summary") or {}).get("focus_score")
        if isinstance(analysis_result.get("summary"), dict)
        else None
    )
    applied: list[dict[str, Any]] = []
    skipped = 0
    for correction in corrections:
        if not isinstance(correction, dict):
            skipped += 1
            continue
        correction_confidence = _number(correction.get("confidence"), overall_confidence)
        new_state = VISION_TO_RULE_STATE.get(str(correction.get("vision_state") or ""))
        if new_state is None or min(overall_confidence, correction_confidence) < minimum_confidence:
            skipped += 1
            continue
        time_sec = _number(correction.get("time_sec"), -1.0)
        row = _find_timeline_row(timeline, time_sec)
        if row is None:
            skipped += 1
            continue
        old_state = str(row.get("state") or "unknown")
        if old_state == new_state:
            skipped += 1
            continue
        _update_row_state(row, new_state)
        applied.append(
            {
                "time_sec": _row_time(row),
                "from_state": old_state,
                "to_state": new_state,
                "confidence": correction_confidence,
            }
        )

    if applied:
        _recalculate_result(analysis_result)
    score_after = _number(
        (analysis_result.get("summary") or {}).get("focus_score")
        if isinstance(analysis_result.get("summary"), dict)
        else None
    )
    return {
        "applied_count": len(applied),
        "skipped_count": skipped,
        "score_before": score_before,
        "score_after": score_after,
        "applied": applied,
    }
