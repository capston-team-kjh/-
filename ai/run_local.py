import json
import cv2
from pathlib import Path

SAMPLING_FPS = 5
OFF_EVENT_SEC = 2.0
PENALTY_PER_SEC = 2  # off일 때 초당 감점

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))

def dummy_gaze_state(frame_idx: int) -> str:
    # TODO: MediaPipe FaceMesh로 on/off/missing 판정으로 교체
    # 지금은 테스트용: 30~50프레임은 off, 나머진 on
    if 30 <= frame_idx <= 50:
        return "off"
    return "on"

def main(video_path: str, out_path: str = "output.json", session_id: str = "S001"):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"VIDEO_NOT_FOUND: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(video_fps / SAMPLING_FPS)))

    timeline = []
    score = 100

    off_run_frames = 0
    off_event_armed = True  # off 상태 들어오면 1회만 카운트하도록

    total_frames = 0
    on_frames = 0
    off_frames = 0
    missing_frames = 0
    off_gaze_count = 0

    frame_idx = -1
    sampled_idx = -1

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        if frame_idx % step != 0:
            continue

        sampled_idx += 1
        t = sampled_idx / SAMPLING_FPS

        gaze_state = dummy_gaze_state(sampled_idx)  # TODO 교체

        # 통계용
        total_frames += 1
        if gaze_state == "on":
            on_frames += 1
        elif gaze_state == "off":
            off_frames += 1
        else:
            missing_frames += 1

        # 이벤트 카운팅
        if gaze_state == "off":
            off_run_frames += 1
            if off_event_armed and off_run_frames >= int(OFF_EVENT_SEC * SAMPLING_FPS):
                off_gaze_count += 1
                off_event_armed = False
        else:
            off_run_frames = 0
            off_event_armed = True

        # 점수
        if gaze_state == "off":
            score = clamp(score - int(round(PENALTY_PER_SEC / SAMPLING_FPS)))
        timeline.append({"t": round(t, 3), "gaze_state": gaze_state, "score": score})

    cap.release()

    focused_sec = int(round(on_frames / SAMPLING_FPS))
    missing_sec = int(round(missing_frames / SAMPLING_FPS))
    avg_score = round(sum(x["score"] for x in timeline) / max(1, len(timeline)), 1)

    out = {
        "schema_version": "v1",
        "session_id": session_id,
        "sampling_fps": SAMPLING_FPS,
        "timeline": timeline,
        "summary": {
            "avg_score": avg_score,
            "focused_sec": focused_sec,
            "off_gaze_count": off_gaze_count,
            "missing_sec": missing_sec
        }
    }

    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--out", default="output.json")
    p.add_argument("--session-id", default="S001")
    args = p.parse_args()
    main(args.video, args.out, args.session_id)
