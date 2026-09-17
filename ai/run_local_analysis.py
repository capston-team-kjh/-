import json
from pathlib import Path

from focus_ai.analyze import (
    AnalyzeConfig,
    analyze_absent,
    analyze_merged_video,
    _write_summary_csv,
    _write_timeline_csv,
    _write_events_csv,
)

VIDEO_PATH = r"C:\Users\wkdgu\Videos\Captures\test6.mp4"
SESSION_ID = "NORMAL_STUDY_001"

print("video path:", VIDEO_PATH)
print("video exists:", Path(VIDEO_PATH).exists())

config = AnalyzeConfig(
    use_trained_classifier=False,
    sampling_fps=1,
)

# 일반 웹캠 영상이면 False
# 좌측 얼굴 + 우측 책상 합본 영상이면 True
IS_MERGED_VIDEO = True

if IS_MERGED_VIDEO:
    result = analyze_merged_video(
        SESSION_ID,
        VIDEO_PATH,
        config,
    )
else:
    result = analyze_absent(
        SESSION_ID,
        VIDEO_PATH,
        "front",
        config,
    )

from focus_ai.vision import validate_analysis_with_vision

result = validate_analysis_with_vision(VIDEO_PATH, result)

output_dir = Path("local_outputs")
output_dir.mkdir(exist_ok=True)

json_path = output_dir / f"{SESSION_ID}_result.json"
summary_csv_path = output_dir / f"{SESSION_ID}_summary.csv"
timeline_csv_path = output_dir / f"{SESSION_ID}_timeline.csv"
events_csv_path = output_dir / f"{SESSION_ID}_events.csv"

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

_write_summary_csv(result, str(summary_csv_path))
_write_timeline_csv(result, str(timeline_csv_path))
_write_events_csv(result, str(events_csv_path))

print("status:", result.get("status"))
print("summary:", result.get("summary"))
print("events:", result.get("events")[:10])
print("saved:", json_path)
