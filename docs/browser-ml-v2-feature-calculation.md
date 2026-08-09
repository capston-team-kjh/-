# Browser ML v2 Feature Calculation

Browser ML v2의 34개 feature는 프런트엔드에서 실제 계산된다.

## 호출 흐름

`study-session.tsx`
→ `extractFrontMeasurements()`
→ `FrontV2FeaturePipeline.process()`
→ 34개 feature vector 생성

34개 feature 목록은 `focus-state-v2.schema.json`에 정의되어 있다.

## 계산 파일별 feature

### `continuous-features.ts`

- `left_ear`
- `right_ear`
- `avg_ear`
- `iris_x_ratio`
- `iris_y_ratio`
- `face_head_down_ratio`
- `face_head_tilt_ratio`
- `pose_head_drop_ratio`
- `pose_head_tilt_ratio`
- `shoulder_slope`
- `face_seen`
- `pose_seen`

### `personal-normalization.ts`

- `normalized_left_ear`
- `normalized_right_ear`
- `normalized_avg_ear`

### `temporal-window.ts`

- `ear_rolling_mean`
- `ear_rolling_min`
- `ear_rolling_std`
- `ear_slope`
- `continuous_eye_closed_sec`
- `gaze_x_rolling_mean`
- `gaze_y_rolling_mean`
- `gaze_x_rolling_std`
- `gaze_y_rolling_std`

### `front-v2-pipeline.ts`

- `gaze_x_delta_from_baseline`
- `gaze_y_delta_from_baseline`
- `face_head_down_delta`
- `face_head_tilt_delta`
- `pose_head_drop_delta`
- `pose_head_tilt_delta`
- `shoulder_slope_delta`
- `face_valid_ratio`
- `pose_valid_ratio`
- `calibration_valid`
- 최종 34개 feature 조립

## 주요 10개 feature 계산

1. `left_ear`
   - 파일: `continuous-features.ts`
   - 함수: `calculateEar()`
   - 눈의 가로 길이와 세 쌍의 세로 landmark 거리 평균 비율을 사용한다.

2. `iris_x_ratio`
   - 파일: `continuous-features.ts`
   - 함수: `calculateIrisRatios()`
   - 양쪽 눈 각각에서 홍채 중심의 가로 상대 위치를 계산한 뒤 평균을 사용한다.

3. `face_head_down_ratio`
   - 파일: `continuous-features.ts`
   - 눈 중간점, 코, 턱 landmark를 이용해 계산한다.

4. `pose_head_drop_ratio`
   - 파일: `continuous-features.ts`
   - 코와 양쪽 어깨 위치 및 어깨 너비를 이용해 계산한다.

5. `shoulder_slope`
   - 파일: `continuous-features.ts`
   - 좌우 어깨의 y 좌표 차이의 절댓값이다.

6. `normalized_avg_ear`
   - 파일: `personal-normalization.ts`
   - 개인 baseline의 median과 IQR을 사용한다.
   - 계산식: `(현재값 - baseline median) / max(IQR, minimumScale)`

7. `ear_rolling_mean`
   - 파일: `temporal-window.ts`
   - temporal window 안의 유효한 `avgEar` 값들의 평균이다.

8. `gaze_x_delta_from_baseline`
   - 파일: `front-v2-pipeline.ts`
   - 계산식: `현재 irisXRatio - 개인 baseline median`

9. `face_valid_ratio`
   - 파일: `front-v2-pipeline.ts`
   - 최근 quality window의 `faceSeen` 값 중 `true` 비율이다.

10. `calibration_valid`
    - 파일: `front-v2-pipeline.ts`
    - `BASELINE_KEYS`의 10개 feature가 모두 정규화 가능한 경우 `1`이다.
    - 하나라도 정규화할 수 없으면 `0`이다.

## `calibration_valid`의 최종 판정

`calibration_valid`는 `CausalPersonalNormalizer`가 반환하는 개별 `calibrationValid` 값을 그대로 사용하는 것이 아니다. `FrontV2FeaturePipeline.process()`에서 아래 조건으로 최종 계산된다.

```ts
BASELINE_KEYS.every((key) => personal.values[key] !== null)
```

즉, `BASELINE_KEYS`에 속한 10개 feature 모두에 대해 개인 정규화 값이 존재할 때만 `calibration_valid`가 `1`이 된다.
