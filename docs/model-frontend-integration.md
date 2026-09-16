# 모델 + 학습 연산 + 프런트 적용 인계

이 문서와 아래 링크는 같은 release 브랜치 기준이다. **ONNX만 복사하지 말고 전처리와 최종 판정 코드도 함께 적용해야 한다.** 이번 인계는 기존 모델을 유지하며, 재학습 또는 학습/브라우저 전처리의 동등성을 새로 검증한 결과가 아니다.

## 가져갈 파일

| 역할 | 파일 |
| --- | --- |
| 브라우저에서 로드할 실제 모델 | [focus_classifier.onnx](../frontend/public/focus_classifier.onnx) |
| 모델 입력 계산 및 ONNX 호출 구현 | [study-session.tsx](../frontend/src/pages/study-session.tsx) |
| 개인 보정·지속 시간·최종 상태 결정 | [production-decision.mjs](../frontend/src/ai/production-decision.mjs) |
| TypeScript 선언 | [production-decision.d.mts](../frontend/src/ai/production-decision.d.mts) |
| 얼굴/홍채 및 포즈 추출 모델 | [face_landmarker.task](../frontend/public/face_landmarker.task), [pose_landmarker.task](../frontend/public/pose_landmarker.task) |
| 기존 Python 학습 진입점·입력 순서·라벨 생성 | [train_state_classifier.py](../ai/train_state_classifier.py) |
| Python 원본 영상 분석·규칙·수학 | [analyze.py](../ai/focus_ai/analyze.py) |
| 학습 알고리즘 수학 | [simple_state_classifier.py](../ai/focus_ai/simple_state_classifier.py) |
| 기존 ONNX 변환 코드 (참고용, 실행 시 출력 경로 주의) | [onnx_conversion.py](../ai/models/onnx_conversion.py) |
| 학습 기록 | [summary.json](../ai/state_classifier_training/summary.json) |
| 적용/배포 체크리스트 | [production-focus-model-handoff.md](production-focus-model-handoff.md) |

이미 저장소에 있는 모델/학습 소스는 중복 복사하지 않았다. GitHub에서 모델 파일을 다운로드할 때 HTML 페이지가 아닌 Raw 파일을 받아야 한다.

## 입력·출력 계약

입력 `float_input`: float32 `[1,16]`. 영상이나 랜드마크를 직접 넣는 모델이 아니라 아래 **0/1 플래그**를 넣는다. 별도 표준화 연산은 현재 브라우저 코드에 없다.

| 인덱스 | feature | 현재 브라우저 생성 방법 |
| ---: | --- | --- |
| 0 | is_front_camera | 1 고정 |
| 1 | is_overhead_camera | 1 고정 |
| 2 | face_seen | 전면 얼굴 검출 |
| 3 | gaze_side | 전면 홍채 평균 X 비율 ≤0.35 또는 ≥0.65 |
| 4 | gaze_down | 전면 홍채 평균 Y 비율 ≥0.62 (모델 입력용, 최종 상태와 별개) |
| 5 | bad_posture | 전면 어깨 Y 차 ≥0.12 또는 코의 어깨 중심 대비 X 비율 ≥0.18 |
| 6 | eye_closed | 전면 평균 EAR ≤0.16 |
| 7 | blink | 현재 코드에서는 eye_closed와 동일 |
| 8 | long_eye_closure | 최근 10개 샘플 모두 eye_closed |
| 9 | head_down | 전면 코/얼굴 높이 비율 ≥0.72 |
| 10 | head_tilt | 두 눈 Y 차 / 눈 X 폭 ≥0.12 |
| 11 | drowsy | long_eye_closure AND head_down (입력용 proxy) |
| 12 | page_turn | 아래 손 이동 규칙 |
| 13 | pen_fidget | 아래 손 이동 규칙 |
| 14 | restless_hand | 아래 손 이동 규칙 |
| 15 | unknown | 0 고정 |

출력 `label`: string `[1]`, `probabilities`: float32 `[1,5]`.
확률 순서: `drowsy, focus, gaze_down, gaze_side, unknown`.
모델 SHA-256: `e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f`.

## 현재 프런트에 옮겨진 계산식

아래 좌표는 MediaPipe 정규화 x/y이며 d(a,b)는 2D 유클리드 거리다. 영상 분석은 약 1초 간격이다. 실제 구현 원본은 study-session.tsx이며 식을 다시 타이핑하기보다 해당 코드를 사용한다.

- 오른쪽 EAR = `(d(159,145)+d(158,153))/(2*d(33,133)+1e-6)`.
- 왼쪽 EAR = `(d(386,374)+d(385,380))/(2*d(362,263)+1e-6)`. 평균을 사용한다.
- 홍채 X = `(iris.x-min(corner.x))/(max(corner.x)-min(corner.x)+1e-6)`. 오른쪽 `(468,33,133)`, 왼쪽 `(473,362,263)` 평균.
- 홍채 Y도 같은 min/max 식이며 오른쪽 `(468,159,145)`, 왼쪽 `(473,386,374)` 평균.
- `eyeMidY=(y33+y263)/2`, `faceHeight=y152-eyeMidY`, 머리 숙임 비율 = `(y1-eyeMidY)/faceHeight`. 유효하지 않은 높이는 NaN으로 처리하여 추론하지 않는다.
- 머리 기울기 = `abs(y33-y263)/abs(x263-x33)`.
- 자세: `abs(pose.y11-pose.y12)` 및 `abs(pose.x0-(pose.x11+pose.x12)/2)/abs(pose.x12-pose.x11)`.
- 손: 책상 포즈의 오른쪽 손목 16 우선, 없으면 전면 포즈 사용. 최근 10개 샘플에서 유효한 인접 쌍 ≥7개일 때 계산한다. 이동 거리 합 L, 처음-마지막 거리 D, X/Y 범위 X/Y, 영역 대각선 B=`hypot(X,Y)`, 연속 단위 이동벡터 내적 <0.2인 횟수 C를 사용한다.
- page_turn: `L≥0.18 && D≥0.14 && X≥0.12 && Y≤0.10 && C≤2`.
- 그 외 pen_fidget: `L≥0.18 && B≤0.12 && C≥3`.
- 그 외 restless_hand: `L≥0.28 && B≥0.18 && C≥2`.

## 학습 당시 규칙/수학과 구별할 점

학습 코드는 Python 분석 결과의 `flags`를 FEATURE_NAMES 순서로 읽고, `rule_state`(없으면 state)를 라벨로 사용한다. 따라서 인간 직접 정답이 아닌 **규칙 의사 라벨 학습**이다. absent/bad_posture 라벨은 제외한다. merged 영상은 전면과 오버헤드를 별도 행으로 추출한다.

SimpleStateClassifier는 Gaussian Naive Bayes다. 클래스별 각 feature 평균 μ와 분산 σ²(하한 1e-4)를 구하고, 균등 prior=1/클래스 수를 사용한다. 추론 점수는 `log(prior) - 0.5*Σlog(2πσ²) - Σ((x-μ)²/(2σ²))`, 확률은 최댓값을 뺀 지수 값을 합으로 나눈다. 이 분류 연산은 ONNX가 담당하므로 프런트에서 재구현하지 않는다.

**동등성 미확인/알려진 차이:** Python 학습은 카메라별 플래그지만 브라우저는 두 카메라 플래그를 동시에 1로 넣는다. 브라우저 blink는 eye_closed와 같고 unknown은 0 고정이며 drowsy 입력은 단순 proxy다. Python 원본의 시간 집계/상태 규칙 전체와 현재 1Hz 브라우저 계산은 동일하다고 보장할 수 없다. 위 표는 '학습 원본과 완전히 같은 계산'이 아니라 **현재 브라우저 코드의 정확한 명세**다. 전처리 동등성 검증 및 그 차이에 따른 정확도 평가는 남아 있다.

## ONNX 이후 최종 판정 (새 런타임 규칙)

production-decision.mjs를 그대로 연결한다. 개인 보정: 정면·눈 뜬 유효 샘플 5개 중앙값. 장기 눈 감김 10초 또는 졸음 확률 ≥0.65 + 눈 감김/손 활동 없는 머리 숙임 5초로 졸음 확정. 눈 감김은 개인 EAR의 0.7배 이하, 머리 숙임은 개인 기준 +0.04 이상이다.

최종 gaze_down은 개인 홍채 Y +0.08 이상 AND 머리 숙임 +0.04 이상이 2초 지속될 때 MediaPipe만 생성한다. ONNX gaze_down 클래스는 존재하지만 최종 상태로 직접 채택하지 않는다. 입력 단절은 지속 증거를 초기화하고 보정/얼굴 신호 부족 시 졸음을 확정하지 않는다.

이 규칙은 기존 모델 학습 수학이 아니라 새 후처리다. 설정은 초기값이며 새 조합의 실사용 정확도는 미검증이다. DB/API 타임라인에는 `{t,state}`만 전달하고 중간 진단은 메모리에만 둔다.

## 확인 명령

의존성 설치 후 저장소 루트에서:

```powershell
node --test frontend/src/ai/production-decision.test.mjs frontend/src/ai/production-model.test.mjs
npm --prefix frontend run build
```

테스트는 계약/판정 동작 확인이며, Python/브라우저 영상 전처리 동등성 또는 실사용 정확도 검증을 대체하지 않는다.
