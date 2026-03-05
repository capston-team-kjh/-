from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


@dataclass
class AnalyzeConfig:
    sampling_fps: int = 5
    absent_threshold_sec: int = 5
    min_face_confidence: float = 0.5
    version: str = "ai-0.2.1"


def _read_video_meta(video_path: str) -> Dict[str, Any]:
    if not os.path.exists(video_path):
        return {
            "ok": False,
            "reason": "VIDEO_NOT_FOUND",
            "video_fps": None,
            "frame_count": None,
            "duration_sec": None,
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "ok": False,
            "reason": "VIDEO_OPEN_FAIL",
            "video_fps": None,
            "frame_count": None,
            "duration_sec": None,
        }

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    if fps is None or fps <= 0 or frame_count is None or frame_count <= 0:
        return {
            "ok": False,
            "reason": "VIDEO_META_INVALID",
            "video_fps": float(fps) if fps else None,
            "frame_count": int(frame_count) if frame_count else None,
            "duration_sec": None,
        }

    duration_sec = frame_count / fps
    return {
        "ok": True,
        "reason": None,
        "video_fps": float(fps),
        "frame_count": int(frame_count),
        "duration_sec": int(duration_sec),
    }


def analyze_dummy(
    session_id: str,
    video_path: str,
    camera_type: str,
    config: AnalyzeConfig,
) -> Dict[str, Any]:
    started = time.time()
    meta = _read_video_meta(video_path)
    processing_time_sec = int(time.time() - started)

    if not meta["ok"]:
        return {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": meta["video_fps"],
                "duration_sec": meta["duration_sec"],
                "processed_frames": 0,
                "processing_time_sec": processing_time_sec,
                "version": config.version,
                "warnings": [],
                "fail_reason": meta["reason"],
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }

    duration_sec: int = meta["duration_sec"]
    processed_frames = duration_sec * config.sampling_fps
    timeline = [{"t": t, "state": "focus"} for t in range(duration_sec)]

    return {
        "session_id": session_id,
        "status": "success",
        "meta": {
            "camera_type": camera_type,
            "sampling_fps": config.sampling_fps,
            "video_fps": meta["video_fps"],
            "duration_sec": duration_sec,
            "processed_frames": processed_frames,
            "processing_time_sec": processing_time_sec,
            "version": config.version,
            "warnings": [],
        },
        "summary": {
            "focus_ratio": 1.0,
            "away_count": 0,
            "away_total_sec": 0,
            "absent_count": 0,
            "absent_total_sec": 0,
            "bad_posture_ratio": 0.0,
        },
        "timeline": timeline,
        "events": [],
    }


def _mark_absent_segments(
    face_seen_by_sec: List[bool],
    absent_threshold_sec: int,
) -> Dict[str, Any]:
    duration_sec = len(face_seen_by_sec)
    states = ["focus"] * duration_sec
    events: List[Dict[str, Any]] = []

    t = 0
    while t < duration_sec:
        if face_seen_by_sec[t]:
            t += 1
            continue

        start = t
        while t < duration_sec and (not face_seen_by_sec[t]):
            t += 1
        end = t  # exclusive

        if (end - start) >= absent_threshold_sec:
            for k in range(start, end):
                states[k] = "absent"
            events.append(
                {
                    "type": "absent",
                    "start_sec": start,
                    "end_sec": end,
                    "score": 1.0,
                }
            )

    absent_total_sec = sum(1 for s in states if s == "absent")
    absent_count = len(events)

    return {
        "states": states,
        "events": events,
        "absent_total_sec": absent_total_sec,
        "absent_count": absent_count,
    }


def _resolve_model_path() -> str:
    # analyze.py는 ai/focus_ai/ 안에 있으니, ai/models/detector.tflite를 안전하게 찾는다
    ai_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(ai_root, "models", "detector.tflite")


def _create_face_detector(model_path: str, min_conf: float) -> vision.FaceDetector:
    # 한글/특수문자 경로에서 네이티브가 path open 실패하는 경우가 있어서 buffer 로딩을 우선 시도
    with open(model_path, "rb") as f:
        model_bytes = f.read()

    try:
        base_options = python.BaseOptions(model_asset_buffer=model_bytes)
    except TypeError:
        # 혹시 mediapipe 버전에서 buffer 인자가 없으면 path fallback
        base_options = python.BaseOptions(model_asset_path=model_path)

    options = vision.FaceDetectorOptions(
        base_options=base_options,
        min_detection_confidence=float(min_conf),
    )
    return vision.FaceDetector.create_from_options(options)


def analyze_absent(
    session_id: str,
    video_path: str,
    camera_type: str,
    config: AnalyzeConfig,
) -> Dict[str, Any]:
    started = time.time()
    meta = _read_video_meta(video_path)

    if not meta["ok"]:
        return {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": meta["video_fps"],
                "duration_sec": meta["duration_sec"],
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": meta["reason"],
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }

    fps: float = meta["video_fps"]
    duration_sec: int = meta["duration_sec"]
    face_seen_by_sec = [False] * max(duration_sec, 0)

    model_path = _resolve_model_path()
    if not os.path.exists(model_path):
        return {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": "MODEL_NOT_FOUND",
                "model_path": model_path,
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": 0,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": [],
                "fail_reason": "VIDEO_OPEN_FAIL",
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }

    step = max(int(round(fps / max(config.sampling_fps, 1))), 1)
    processed_frames = 0
    warnings: List[str] = []
    if config.sampling_fps > fps:
        warnings.append("SAMPLING_FPS_GT_VIDEO_FPS")

    detector: Optional[vision.FaceDetector] = None

    try:
        detector = _create_face_detector(model_path, config.min_face_confidence)

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                processed_frames += 1

                sec = int(frame_idx / fps) if fps > 0 else 0
                if 0 <= sec < duration_sec:
                    # 큰 영상이면 축소해서 속도 확보
                    h, w = frame.shape[:2]
                    if w > 960:
                        scale = 960 / w
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    detection_result = detector.detect(mp_image)
                    if detection_result.detections:
                        face_seen_by_sec[sec] = True

            frame_idx += 1

    except RuntimeError as e:
        # 모델 open 실패 같은 네이티브 에러가 여기로 들어옴
        return {
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "camera_type": camera_type,
                "sampling_fps": config.sampling_fps,
                "video_fps": fps,
                "duration_sec": duration_sec,
                "processed_frames": processed_frames,
                "processing_time_sec": int(time.time() - started),
                "version": config.version,
                "warnings": warnings,
                "fail_reason": "MEDIAPIPE_RUNTIME_ERROR",
                "error": str(e),
                "model_path": model_path,
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }

    finally:
        cap.release()
        if detector is not None:
            detector.close()

    seg = _mark_absent_segments(face_seen_by_sec, int(config.absent_threshold_sec))
    states = seg["states"]
    events = seg["events"]
    absent_total_sec = seg["absent_total_sec"]
    absent_count = seg["absent_count"]

    timeline = [{"t": t, "state": states[t]} for t in range(duration_sec)]

    focus_ratio = 1.0
    if duration_sec > 0:
        focus_ratio = max(0.0, 1.0 - (absent_total_sec / duration_sec))

    return {
        "session_id": session_id,
        "status": "success",
        "meta": {
            "camera_type": camera_type,
            "sampling_fps": config.sampling_fps,
            "video_fps": fps,
            "duration_sec": duration_sec,
            "processed_frames": processed_frames,
            "processing_time_sec": int(time.time() - started),
            "version": config.version,
            "warnings": warnings,
            "model_path": model_path,
        },
        "summary": {
            "focus_ratio": float(focus_ratio),
            "away_count": 0,
            "away_total_sec": 0,
            "absent_count": int(absent_count),
            "absent_total_sec": int(absent_total_sec),
            "bad_posture_ratio": 0.0,
        },
        "timeline": timeline,
        "events": events,
    }