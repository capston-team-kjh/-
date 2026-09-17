# Analysis output spec v1

- 시간 단위: 초(seconds)
- timeline 간격: 1 / sampling_fps
- gaze_state: on | off | missing
- score: 0~100 (정수)

summary 규칙(권장)
- focused_sec: gaze_state == on 시간 합
- missing_sec: gaze_state == missing 시간 합
- off_gaze_count: off가 N초 이상 연속이면 1회(중복 카운트 방지)
