# AI 분석 성능 평가

`ai.evaluate`는 기존 영상 분석 결과 JSON과 사람이 작성한 정답 라벨 JSON을 비교한다. DB는 사용하거나 변경하지 않는다.

## 실행

저장소 루트에서 다음 명령을 실행한다.

```powershell
python -m ai.evaluate `
  --prediction predictions/session_001_result.json `
  --label labels/session_001_labels.json
```

전체 지표가 콘솔에 JSON으로 출력되고 `evaluation_results/session_001_metrics.json`에도 저장된다. 경로는 `--output <path>`로 바꿀 수 있고, 파일 저장 없이 출력만 하려면 `--no-save`를 사용한다.

이벤트 매칭 기준은 같은 상태명의 실제/예측 이벤트 간 시간 IoU 0.5 이상이다. 필요하면 `--event-iou-threshold 0.3`처럼 변경한다. 분류 비교 간격은 기존 timeline에 맞춘 1초이며 `--sample-sec`로 변경할 수 있다.

## 수동 라벨 포맷

스키마는 `ai/spec/evaluation_label_v1.schema.json`, 작성 예시는 `labels/session_001_labels.json`에 있다.

- `timeline`: `start_sec` 이상, `end_sec` 미만인 단일 정답 상태 구간이다. 전체 영상 구간을 겹침 없이 라벨링하는 것을 권장한다.
- `events`: 행동 이벤트의 `state`, `start_sec`, `end_sec` 목록이다.
- `event_states`: 이벤트 성능에 포함할 상태명이다. 지정하지 않으면 `absent`, `drowsy`, `gaze_side`, `gaze_down`, `bad_posture`를 평가한다.
- `human_focus_score`: 사람이 영상 전체를 보고 평가한 0~100점 집중도다.
- 기존 분석 결과처럼 `{ "t": 0, "state": "focus" }` 형태의 1초 단위 수동 timeline도 허용한다.

라벨이 없는 시간 구간은 분류 및 지속 시간 평가에서 제외된다. 예측 이벤트의 `overhead_no_activity` 같은 보조 이벤트는 `event_states`에 명시하지 않는 한 이벤트 지표에 포함되지 않는다.

## 지표 해석

- 상태 분류: Accuracy, 클래스별 Precision/Recall/F1, macro F1, weighted F1과 confusion matrix를 제공한다.
- 지속 시간: 라벨이 있는 구간에서 상태별 실제/예측 시간과 절대 오차를 계산한다. `mae_sec`는 출력된 상태별 절대 오차의 평균이다.
- 이벤트 탐지: 동일 상태 이벤트를 시간 IoU 기준으로 일대일 매칭하고 Precision/Recall/F1을 계산한다.
- 집중도 점수: 사람 점수와 `summary.focus_score`의 MAE/RMSE를 계산한다. 한 세션에서는 두 값이 같고, 여러 세션 보고 시 세션별 오차를 다시 평균한다.
- 처리 성능: `meta.duration_sec`, `meta.processing_time_sec`를 사용한다. `speed_ratio = 분석 시간 / 영상 길이`이므로 작을수록 빠르다. `analysis_started_at`, `analysis_ended_at`이 있으면 결과에도 보존한다.
