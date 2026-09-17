# Analysis Rules

이 문서는 `ai/focus_ai/analyze.py`와 `ai/analyzer/focus_score.py`에서 확인한 현재 기준을 그대로 정리한다. 기준 개선이나 변경 제안은 포함하지 않는다.

## 기본 설정

`AnalyzeConfig` 기본값:

- `sampling_fps`: 1
- `absent_threshold_sec`: 5
- `min_face_confidence`: 0.5
- `away_ratio_threshold`: 0.35
- `gaze_side_left_threshold`: 0.35
- `gaze_side_right_threshold`: 0.65
- `gaze_down_threshold`: 0.62
- `bad_posture_min_duration_sec`: 2
- `gaze_side_min_duration_sec`: 2
- `gaze_down_min_duration_sec`: 2
- `drowsy_min_duration_sec`: 10
- `long_eye_closure_min_sec`: 10
- `drowsy_head_motion_threshold`: 0.035
- `classifier_confidence_threshold`: 0.65

## 상태 판정

- `focus`: 다른 상태로 마킹되지 않은 기본 상태이다. `timeline[*].state == "focus"`인 초의 합이 `focus_total_sec`이고, `focus_ratio = focus_total_sec / duration_sec`이다.
- `absent`: 얼굴이 보이지 않는 연속 구간 길이가 `absent_threshold_sec` 이상이면 해당 구간을 `absent`로 표시한다. merged 분석에서는 overhead 활동 또는 사람 흔적이 있으면 `unknown` 또는 `drowsy`로 보정될 수 있다.
- `away`: 최종 summary에서 `away_count`, `away_total_sec`는 현재 `gaze_side`의 count/time alias로 기록된다. 점수 계산에서는 명시적 `gaze_away_total_sec`가 없으면 `away_total_sec` 또는 `gaze_side_total_sec`에 `gaze_down_total_sec`를 더해 `gaze_away` 시간으로 사용한다.
- `bad_posture`: pose landmark의 양쪽 어깨 기울기 또는 코의 어깨 중심 대비 좌우 치우침이 threshold 이상이면 후보가 된다. 최소 2초 이상 지속된 후보만 상태로 반영된다. `bad_posture_ratio = bad_posture_total_sec / duration_sec`.
- `gaze_side`: iris x 위치가 왼쪽 threshold 이하 또는 오른쪽 threshold 이상이거나, 코의 눈 중심 대비 offset이 `away_ratio_threshold` 이상이면 후보가 된다. 최소 2초 이상 지속된 후보만 상태로 반영된다.
- `gaze_down`: iris y 위치 평균이 `gaze_down_threshold` 이상이면 후보가 된다. 최소 2초 이상 지속된 후보만 상태로 반영된다.
- `eyes_closed_long`: 두 눈이 모두 감긴 상태가 `long_eye_closure_min_sec` 이상 지속된 구간이다. summary에는 `long_eye_closure_count`, `long_eye_closure_total_sec`로 기록되고 timeline flags에는 `long_eye_closure`로 표시된다.
- `drowsy`: `long_eye_closure`와 `head_down`이 동시에 참이고, 해당 구간의 head motion 평균이 `drowsy_head_motion_threshold` 이하이면 raw drowsy 후보가 된다. 후보가 `drowsy_min_duration_sec` 이상 지속되면 `drowsy` 상태로 반영된다. merged 분석에서는 overhead 활동이 가까운 시간에 있으면 drowsy를 `bad_posture` 또는 `focus`로 억제할 수 있다.

## 상태 우선 처리

단일 카메라 분석에서 상태는 대략 다음 순서로 반영된다.

1. 얼굴 미검출 구간을 `absent` 또는 drowsy context 기반 `drowsy`로 표시한다.
2. 아직 `focus`인 초에 `gaze_side`를 표시한다.
3. 아직 `focus`인 초에 `drowsy`를 표시한다.
4. 아직 `focus`인 초에 `gaze_down`을 표시한다.
5. 아직 `focus`인 초에 `bad_posture`를 표시한다.
6. 아직 `focus`인데 얼굴이 보이지 않으면 `unknown` 후보로 표시한다.
7. rule-only 상태인 `absent`, `bad_posture`는 classifier가 덮어쓰지 않는다. 그 외 상태는 classifier confidence가 threshold 이상이면 model state를 사용할 수 있다.

## 점수 계산

`calculate_focus_score(summary, total_time_sec)` 기준:

상태 가중치:

- `focus`: 100
- `bad_posture`: 60
- `gaze_away`: 40
- `unknown`: 50
- `present_unknown`: 50
- `drowsy`: 20
- `sleep_suspect`: 20
- `absent`: 0

이벤트 패널티:

- `absent_count * 2.0`
- `drowsy_count * 1.5`
- `sleep_suspect_count * 1.5`
- `gaze_away_count * 1.0`
- `bad_posture_count * 0.5`
- 최대 패널티는 10점

시간 보정 우선순위:

`absent` -> `drowsy` -> `sleep_suspect` -> `gaze_away` -> `bad_posture` -> `unknown` -> `present_unknown` -> `focus`

계산식:

```text
weighted_base_score =
  sum(corrected_state_seconds[state] * STATE_WEIGHTS[state]) / total_time_sec

event_penalty =
  min(raw_event_penalty, 10.0)

focus_score =
  round(clamp(weighted_base_score - event_penalty, 0, 100))
```

`total_time_sec`가 없거나 0이면 `focus_score`는 0이고 warning이 추가된다.
