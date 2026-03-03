from __future__ import annotations

import os
import time
import tempfile
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List

import cv2
import mediapipe as mp

# mediapipe 0.10.x (py3.12)에서 mp.solutions가 __init__에 노출되지 않는 경우 대응
if not hasattr(mp, "solutions"):
    try:
        from mediapipe.python import solutions as mp_solutions  # type: ignore
        mp.solutions = mp_solutions
    except Exception:
        # tasks만 노출되는 빌드/환경일 수도 있음
        mp.solutions = None


@dataclass
class AnalyzeConfig:
    sampling_fps: int = 5
    absent_threshold_sec: int = 5
    min_face_confidence: float = 0.5
    version: str = "ai-0.2.0"


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
        end = t  # end는 "끝 다음 초"(exclusive)

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
    absent_count = sum(1 for e in events if e["type"] == "absent")

    return {
        "states": states,
        "events": events,
        "absent_total_sec": absent_total_sec,
        "absent_count": absent_count,
    }


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

    warnings: List[str] = []
    if config.sampling_fps > fps:
        warnings.append("SAMPLING_FPS_GT_VIDEO_FPS")

    face_seen_by_sec = [False] * max(duration_sec, 0)

    cap = cv2.VideoCapture(video_path)
    step = max(int(round(fps / max(config.sampling_fps, 1))), 1)
    processed_frames = 0

    # 1) mediapipe solutions가 있으면 face_detection 사용
    can_use_mp = False
    try:
        can_use_mp = (mp.solutions is not None) and hasattr(mp.solutions, "face_detection")
    except Exception:
        can_use_mp = False

    if can_use_mp:
        mp_fd = mp.solutions.face_detection
        with mp_fd.FaceDetection(
            model_selection=0,
            min_detection_confidence=float(config.min_face_confidence),
        ) as fd:
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % step == 0:
                    processed_frames += 1
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = fd.process(rgb)

                    sec = int(frame_idx / fps) if fps > 0 else 0
                    if 0 <= sec < duration_sec and res.detections:
                        face_seen_by_sec[sec] = True

                frame_idx += 1

    # 2) 아니면 OpenCV Haar cascade로 fallback (한글 경로 문제 회피를 위해 TEMP로 복사해서 로드)
    else:
        warnings.append("USING_OPENCV_HAAR_FALLBACK")

        src = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        # TEMP는 보통 영문 경로라서 OpenCV가 잘 연다
        dst = os.path.join(tempfile.gettempdir(), "haarcascade_frontalface_default.xml")

        try:
            # dst가 없거나, src가 더 최신이면 복사
            if (not os.path.exists(dst)) or (os.path.getmtime(src) > os.path.getmtime(dst)):
                shutil.copyfile(src, dst)
        except Exception:
            cap.release()
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
                    "warnings": warnings + ["HAAR_CASCADE_COPY_FAIL"],
                    "fail_reason": "HAAR_CASCADE_COPY_FAIL",
                },
                "summary": {},
                "timeline": [],
                "events": [],
            }

        cascade_path = os.path.abspath(dst).replace("\\", "/")

        face_cascade = cv2.CascadeClassifier()
        ok = face_cascade.load(cascade_path)

        if (not ok) or face_cascade.empty():
            cap.release()
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
                    "warnings": warnings + ["HAAR_CASCADE_LOAD_FAIL"],
                    "fail_reason": "HAAR_CASCADE_LOAD_FAIL",
                },
                "summary": {},
                "timeline": [],
                "events": [],
            }

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                processed_frames += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30),
                )

                sec = int(frame_idx / fps) if fps > 0 else 0
                if 0 <= sec < duration_sec and len(faces) > 0:
                    face_seen_by_sec[sec] = True

            frame_idx += 1

    cap.release()

    seg = _mark_absent_segments(face_seen_by_sec, int(config.absent_threshold_sec))
    states = seg["states"]
    events = seg["events"]
    absent_total_sec = seg["absent_total_sec"]
    absent_count = seg["absent_count"]

    timeline = [{"t": t, "state": states[t]} for t in range(duration_sec)]

    focus_ratio = 1.0
    if duration_sec > 0:
        focus_ratio = max(0.0, 1.0 - (absent_total_sec / duration_sec))

    processing_time_sec = int(time.time() - started)

    return {
        "session_id": session_id,
        "status": "success",
        "meta": {
            "camera_type": camera_type,
            "sampling_fps": config.sampling_fps,
            "video_fps": fps,
            "duration_sec": duration_sec,
            "processed_frames": processed_frames,
            "processing_time_sec": processing_time_sec,
            "version": config.version,
            "warnings": warnings,
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
