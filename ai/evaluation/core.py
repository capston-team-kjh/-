from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from statistics import median
from typing import Any, Iterable


DEFAULT_STATES = (
    "focus",
    "absent",
    "drowsy",
    "gaze_side",
    "gaze_down",
    "bad_posture",
    "unknown",
)
DEFAULT_EVENT_STATES = (
    "absent",
    "drowsy",
    "gaze_side",
    "gaze_down",
    "bad_posture",
)


class EvaluationError(ValueError):
    """Raised when prediction or label data cannot be evaluated safely."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise EvaluationError(f"{field} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EvaluationError(f"{field} must be a number") from exc
    if not math.isfinite(result):
        raise EvaluationError(f"{field} must be finite")
    return result


def _state(row: dict[str, Any], field: str) -> str:
    value = row.get("state")
    if value is None:
        value = row.get("type") or row.get("event_type")
    state = str(value or "").strip()
    if not state:
        raise EvaluationError(f"{field} is missing state")
    return state


def _duration_from(data: dict[str, Any], field: str) -> float | None:
    candidates = (
        data.get("video_duration_sec"),
        data.get("duration_sec"),
        (data.get("meta") or {}).get("duration_sec")
        if isinstance(data.get("meta"), dict)
        else None,
    )
    for value in candidates:
        if value is not None:
            duration = _number(value, field)
            if duration <= 0:
                raise EvaluationError(f"{field} must be greater than zero")
            return duration
    return None


def _validate_intervals(
    intervals: list[dict[str, Any]], source: str
) -> list[dict[str, Any]]:
    intervals.sort(key=lambda row: (row["start_sec"], row["end_sec"]))
    previous_end = -1.0
    for index, row in enumerate(intervals):
        if row["start_sec"] < previous_end - 1e-9:
            raise EvaluationError(
                f"{source} timeline overlaps at sorted interval {index}"
            )
        previous_end = max(previous_end, row["end_sec"])
    return intervals


def _timeline_intervals(
    timeline: Any,
    duration_sec: float,
    source: str,
) -> list[dict[str, Any]]:
    if not isinstance(timeline, list) or not timeline:
        raise EvaluationError(f"{source}.timeline must be a non-empty array")
    if not all(isinstance(row, dict) for row in timeline):
        raise EvaluationError(f"{source}.timeline items must be objects")

    interval_rows = all(
        "start_sec" in row and "end_sec" in row for row in timeline
    )
    point_rows = all("t" in row for row in timeline)
    if not interval_rows and not point_rows:
        raise EvaluationError(
            f"{source}.timeline must consistently use start_sec/end_sec or t"
        )

    result: list[dict[str, Any]] = []
    if interval_rows:
        for index, row in enumerate(timeline):
            start = _number(row.get("start_sec"), f"{source}.timeline[{index}].start_sec")
            end = _number(row.get("end_sec"), f"{source}.timeline[{index}].end_sec")
            if start < 0 or end <= start:
                raise EvaluationError(
                    f"{source}.timeline[{index}] must satisfy 0 <= start_sec < end_sec"
                )
            if start >= duration_sec:
                continue
            result.append(
                {
                    "start_sec": start,
                    "end_sec": min(end, duration_sec),
                    "state": _state(row, f"{source}.timeline[{index}]"),
                }
            )
    else:
        points: list[tuple[float, str]] = []
        for index, row in enumerate(timeline):
            timestamp = _number(row.get("t"), f"{source}.timeline[{index}].t")
            if timestamp < 0:
                raise EvaluationError(f"{source}.timeline[{index}].t must be non-negative")
            points.append((timestamp, _state(row, f"{source}.timeline[{index}]")))
        points.sort(key=lambda item: item[0])
        if any(points[index][0] <= points[index - 1][0] for index in range(1, len(points))):
            raise EvaluationError(f"{source}.timeline t values must be unique")
        differences = [
            points[index][0] - points[index - 1][0]
            for index in range(1, len(points))
        ]
        inferred_step = median(differences) if differences else 1.0
        for index, (start, state) in enumerate(points):
            if start >= duration_sec:
                continue
            end = points[index + 1][0] if index + 1 < len(points) else start + inferred_step
            end = min(end, duration_sec)
            if end > start:
                result.append({"start_sec": start, "end_sec": end, "state": state})

    if not result:
        raise EvaluationError(f"{source}.timeline has no interval inside video duration")
    return _validate_intervals(result, source)


def _ordered_states(
    label: dict[str, Any],
    label_intervals: list[dict[str, Any]],
    prediction_intervals: list[dict[str, Any]],
) -> list[str]:
    ordered: list[str] = list(DEFAULT_STATES)
    configured = label.get("states")
    if configured is not None:
        if not isinstance(configured, list):
            raise EvaluationError("label.states must be an array")
        ordered.extend(str(value) for value in configured if str(value).strip())
    ordered.extend(row["state"] for row in label_intervals)
    ordered.extend(row["state"] for row in prediction_intervals)
    return list(dict.fromkeys(ordered))


def _state_at(intervals: list[dict[str, Any]], timestamp: float) -> str | None:
    for row in intervals:
        if row["start_sec"] <= timestamp < row["end_sec"]:
            return row["state"]
        if row["start_sec"] > timestamp:
            break
    return None


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _classification_metrics(
    label_intervals: list[dict[str, Any]],
    prediction_intervals: list[dict[str, Any]],
    states: list[str],
    duration_sec: float,
    sample_sec: float,
) -> dict[str, Any]:
    if sample_sec <= 0:
        raise EvaluationError("sample_sec must be greater than zero")
    matrix: dict[str, dict[str, int]] = {
        actual: {predicted: 0 for predicted in states} for actual in states
    }
    unmatched_label_samples = 0
    sample_count = 0
    step_count = int(math.ceil(duration_sec / sample_sec))
    for index in range(step_count):
        timestamp = index * sample_sec
        actual = _state_at(label_intervals, timestamp)
        if actual is None:
            continue
        predicted = _state_at(prediction_intervals, timestamp)
        if predicted is None:
            unmatched_label_samples += 1
            continue
        matrix.setdefault(actual, {}).setdefault(predicted, 0)
        if predicted not in states:
            for row in matrix.values():
                row.setdefault(predicted, 0)
            states.append(predicted)
        matrix[actual][predicted] += 1
        sample_count += 1

    if sample_count == 0:
        raise EvaluationError("prediction and label timelines have no comparable samples")

    per_class: dict[str, dict[str, Any]] = {}
    correct = 0
    active_precision: list[float] = []
    active_recall: list[float] = []
    active_f1: list[float] = []
    weighted_precision_sum = 0.0
    weighted_recall_sum = 0.0
    weighted_f1_sum = 0.0
    total_support = 0
    for state in states:
        tp = matrix.get(state, {}).get(state, 0)
        fp = sum(matrix.get(actual, {}).get(state, 0) for actual in states if actual != state)
        fn = sum(matrix.get(state, {}).get(predicted, 0) for predicted in states if predicted != state)
        support = sum(matrix.get(state, {}).values())
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class[state] = {
            "precision": _rounded(precision),
            "recall": _rounded(recall),
            "f1": _rounded(f1),
            "support": support,
        }
        if support > 0 or fp > 0:
            active_precision.append(precision)
            active_recall.append(recall)
            active_f1.append(f1)
        weighted_precision_sum += precision * support
        weighted_recall_sum += recall * support
        weighted_f1_sum += f1 * support
        total_support += support
        correct += tp

    macro_precision = _safe_div(sum(active_precision), len(active_precision))
    macro_recall = _safe_div(sum(active_recall), len(active_recall))
    macro_f1 = _safe_div(sum(active_f1), len(active_f1))
    return {
        "sample_interval_sec": _rounded(sample_sec),
        "sample_count": sample_count,
        "unmatched_label_samples": unmatched_label_samples,
        "accuracy": _rounded(_safe_div(correct, sample_count)),
        "averaging": "macro",
        "precision": _rounded(macro_precision),
        "recall": _rounded(macro_recall),
        "f1": _rounded(macro_f1),
        "macro_precision": _rounded(macro_precision),
        "macro_recall": _rounded(macro_recall),
        "macro_f1": _rounded(macro_f1),
        "weighted_precision": _rounded(
            _safe_div(weighted_precision_sum, total_support)
        ),
        "weighted_recall": _rounded(_safe_div(weighted_recall_sum, total_support)),
        "weighted_f1": _rounded(_safe_div(weighted_f1_sum, total_support)),
        "per_class": per_class,
        "confusion_matrix": {
            actual: {predicted: matrix.get(actual, {}).get(predicted, 0) for predicted in states}
            for actual in states
        },
    }


def _overlap_duration(
    first: dict[str, Any], second: dict[str, Any]
) -> float:
    return max(
        0.0,
        min(first["end_sec"], second["end_sec"])
        - max(first["start_sec"], second["start_sec"]),
    )


def _duration_metrics(
    label_intervals: list[dict[str, Any]],
    prediction_intervals: list[dict[str, Any]],
    states: list[str],
) -> dict[str, Any]:
    actual = Counter()
    predicted = Counter()
    for label_row in label_intervals:
        actual[label_row["state"]] += label_row["end_sec"] - label_row["start_sec"]
        for prediction_row in prediction_intervals:
            overlap = _overlap_duration(label_row, prediction_row)
            if overlap:
                predicted[prediction_row["state"]] += overlap

    per_state: dict[str, dict[str, float]] = {}
    errors: list[float] = []
    for state in states:
        actual_sec = float(actual[state])
        predicted_sec = float(predicted[state])
        signed_error = predicted_sec - actual_sec
        absolute_error = abs(signed_error)
        errors.append(absolute_error)
        per_state[state] = {
            "actual_sec": _rounded(actual_sec),
            "predicted_sec": _rounded(predicted_sec),
            "error_sec": _rounded(signed_error),
            "absolute_error_sec": _rounded(absolute_error),
        }
    return {
        "annotated_duration_sec": _rounded(sum(actual.values())),
        "mae_sec": _rounded(_safe_div(sum(errors), len(errors))),
        "total_absolute_error_sec": _rounded(sum(errors)),
        "per_state": per_state,
    }


def _events(data: dict[str, Any], source: str) -> list[dict[str, Any]]:
    raw_events = data.get("events", [])
    if not isinstance(raw_events, list):
        raise EvaluationError(f"{source}.events must be an array")
    result = []
    for index, row in enumerate(raw_events):
        if not isinstance(row, dict):
            raise EvaluationError(f"{source}.events[{index}] must be an object")
        start = _number(row.get("start_sec"), f"{source}.events[{index}].start_sec")
        end = _number(row.get("end_sec"), f"{source}.events[{index}].end_sec")
        if start < 0 or end <= start:
            raise EvaluationError(
                f"{source}.events[{index}] must satisfy 0 <= start_sec < end_sec"
            )
        result.append(
            {
                "state": _state(row, f"{source}.events[{index}]"),
                "start_sec": start,
                "end_sec": end,
            }
        )
    return result


def _event_iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    intersection = _overlap_duration(first, second)
    union = (
        first["end_sec"]
        - first["start_sec"]
        + second["end_sec"]
        - second["start_sec"]
        - intersection
    )
    return _safe_div(intersection, union)


def _event_metrics(
    actual_events: list[dict[str, Any]],
    predicted_events: list[dict[str, Any]],
    event_states: list[str],
    iou_threshold: float,
) -> dict[str, Any]:
    if not 0 < iou_threshold <= 1:
        raise EvaluationError("event_iou_threshold must be in (0, 1]")
    per_class: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    matched_details: list[dict[str, Any]] = []

    for state in event_states:
        actual = [event for event in actual_events if event["state"] == state]
        predicted = [event for event in predicted_events if event["state"] == state]
        candidates = sorted(
            (
                (_event_iou(actual_row, predicted_row), actual_index, predicted_index)
                for actual_index, actual_row in enumerate(actual)
                for predicted_index, predicted_row in enumerate(predicted)
            ),
            reverse=True,
        )
        used_actual: set[int] = set()
        used_predicted: set[int] = set()
        for iou, actual_index, predicted_index in candidates:
            if iou < iou_threshold:
                break
            if actual_index in used_actual or predicted_index in used_predicted:
                continue
            used_actual.add(actual_index)
            used_predicted.add(predicted_index)
            matched_details.append(
                {
                    "state": state,
                    "actual_start_sec": actual[actual_index]["start_sec"],
                    "actual_end_sec": actual[actual_index]["end_sec"],
                    "predicted_start_sec": predicted[predicted_index]["start_sec"],
                    "predicted_end_sec": predicted[predicted_index]["end_sec"],
                    "iou": _rounded(iou),
                }
            )
        tp = len(used_actual)
        fp = len(predicted) - tp
        fn = len(actual) - tp
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class[state] = {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": _rounded(precision),
            "recall": _rounded(recall),
            "f1": _rounded(f1),
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    precision = _safe_div(total_tp, total_tp + total_fp)
    recall = _safe_div(total_tp, total_tp + total_fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "matching_rule": "same state and temporal IoU at or above threshold",
        "iou_threshold": _rounded(iou_threshold),
        "event_states": event_states,
        "true_positive": total_tp,
        "false_positive": total_fp,
        "false_negative": total_fn,
        "precision": _rounded(precision),
        "recall": _rounded(recall),
        "f1": _rounded(f1),
        "per_class": per_class,
        "matched_events": matched_details,
    }


def _first_number(values: Iterable[tuple[Any, str]]) -> float | None:
    for value, field in values:
        if value is not None:
            return _number(value, field)
    return None


def _timestamp_seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0.0, (end_dt - start_dt).total_seconds())
    except (TypeError, ValueError):
        return None


def _processing_metrics(prediction: dict[str, Any], video_duration_sec: float) -> dict[str, Any]:
    meta = prediction.get("meta") if isinstance(prediction.get("meta"), dict) else {}
    processing = meta.get("processing") if isinstance(meta.get("processing"), dict) else {}
    started_at = (
        meta.get("analysis_started_at")
        or meta.get("started_at")
        or processing.get("started_at")
    )
    ended_at = (
        meta.get("analysis_ended_at")
        or meta.get("ended_at")
        or processing.get("ended_at")
    )
    analysis_time = _first_number(
        (
            (meta.get("total_processing_time_sec"), "meta.total_processing_time_sec"),
            (meta.get("processing_time_sec"), "meta.processing_time_sec"),
            (meta.get("analysis_time_sec"), "meta.analysis_time_sec"),
            (processing.get("duration_sec"), "meta.processing.duration_sec"),
        )
    )
    if analysis_time is None:
        analysis_time = _timestamp_seconds(started_at, ended_at)
    speed_ratio = (
        _safe_div(analysis_time, video_duration_sec) if analysis_time is not None else None
    )
    realtime_multiplier = (
        _safe_div(video_duration_sec, analysis_time)
        if analysis_time is not None and analysis_time > 0
        else None
    )
    return {
        "analysis_started_at": started_at,
        "analysis_ended_at": ended_at,
        "video_duration_sec": _rounded(video_duration_sec),
        "analysis_time_sec": _rounded(analysis_time) if analysis_time is not None else None,
        "speed_ratio": _rounded(speed_ratio) if speed_ratio is not None else None,
        "realtime_multiplier": (
            _rounded(realtime_multiplier) if realtime_multiplier is not None else None
        ),
    }


def evaluate(
    prediction: dict[str, Any],
    label: dict[str, Any],
    *,
    sample_sec: float = 1.0,
    event_iou_threshold: float = 0.5,
) -> dict[str, Any]:
    """Evaluate one prediction JSON object against one manual label object."""
    if not isinstance(prediction, dict) or not isinstance(label, dict):
        raise EvaluationError("prediction and label must be JSON objects")
    prediction_session = str(prediction.get("session_id") or "").strip()
    label_session = str(label.get("session_id") or "").strip()
    if not prediction_session or not label_session:
        raise EvaluationError("prediction.session_id and label.session_id are required")
    if prediction_session != label_session:
        raise EvaluationError(
            f"session_id mismatch: prediction={prediction_session}, label={label_session}"
        )

    label_duration = _duration_from(label, "label.video_duration_sec")
    prediction_duration = _duration_from(prediction, "prediction.meta.duration_sec")
    video_duration_sec = label_duration or prediction_duration
    if video_duration_sec is None:
        raise EvaluationError("video duration is required in label or prediction metadata")

    label_intervals = _timeline_intervals(label.get("timeline"), video_duration_sec, "label")
    prediction_intervals = _timeline_intervals(
        prediction.get("timeline"), video_duration_sec, "prediction"
    )
    states = _ordered_states(label, label_intervals, prediction_intervals)

    event_states_raw = label.get("event_states", list(DEFAULT_EVENT_STATES))
    if not isinstance(event_states_raw, list):
        raise EvaluationError("label.event_states must be an array")
    event_states = list(
        dict.fromkeys(str(value).strip() for value in event_states_raw if str(value).strip())
    )

    human_score = _first_number(
        (
            (label.get("human_focus_score"), "label.human_focus_score"),
            (label.get("focus_score"), "label.focus_score"),
        )
    )
    summary = prediction.get("summary") if isinstance(prediction.get("summary"), dict) else {}
    ai_score = _first_number(
        (
            (summary.get("focus_score"), "prediction.summary.focus_score"),
            (summary.get("concentration_score"), "prediction.summary.concentration_score"),
            (prediction.get("focus_score"), "prediction.focus_score"),
        )
    )
    if human_score is None or ai_score is None:
        raise EvaluationError(
            "human focus score and AI focus_score are required for score validation"
        )
    score_error = ai_score - human_score

    return {
        "schema_version": "evaluation-result-v1",
        "session_id": label_session,
        "classification": _classification_metrics(
            label_intervals,
            prediction_intervals,
            states,
            video_duration_sec,
            _number(sample_sec, "sample_sec"),
        ),
        "duration_error": _duration_metrics(
            label_intervals, prediction_intervals, states
        ),
        "event_detection": _event_metrics(
            _events(label, "label"),
            _events(prediction, "prediction"),
            event_states,
            _number(event_iou_threshold, "event_iou_threshold"),
        ),
        "focus_score_error": {
            "human_score": _rounded(human_score),
            "ai_score": _rounded(ai_score),
            "error": _rounded(score_error),
            "mae": _rounded(abs(score_error)),
            "rmse": _rounded(math.sqrt(score_error * score_error)),
        },
        "processing_time": _processing_metrics(prediction, video_duration_sec),
    }
