# FocusAI Browser ML v2 (offline only)

이 폴더는 브라우저에서 실행할 후보 모델을 개발 PC에서 준비하는 용도다. Production 추론 경로가 아니며 FastAPI, Worker, SQS, S3 영상 분석과 연결하지 않는다.

## 데이터 계약

Python은 별도 특징 목록을 갖지 않고 `frontend/src/ai/contracts/focus-state-v2.schema.json`을 직접 읽는다. 학습 CSV에는 아래 메타데이터와 계약에 적힌 34개 특징이 모두 있어야 한다.

```text
subject_id          익명 피험자 ID (예: SUBJECT_001)
session_id          한 번의 수집 세션 ID
source_id           원본/수집 출처 ID
camera_role         front
environment_id      조명·책상·장소 조건 ID
camera_setup_id     카메라 위치·장치 설정 ID
timestamp_ms        세션 내 프레임 시각
label               drowsy | focus | gaze_down | gaze_side
```

필수 특징의 빈 값, NaN, 무한대는 0으로 대체하지 않고 오류로 중단한다. `unknown`, `absent`, `bad_posture`, 오버헤드 활동은 v2 얼굴 상태 모델의 학습 클래스가 아니다.

`subject_id`가 없는 레거시 데이터는 `--allow-legacy-subjects`로만 읽을 수 있고 `subject_generalization_verifiable=false`로 기록된다. 하나의 레거시 ID를 여러 사람으로 추정하지 않는다. 따라서 해당 데이터만으로는 후보 승격 조건을 충족할 수 없다.

하나의 `session_id` 또는 `source_id`가 여러 `subject_id`에 속하면 원본 누수 가능성이 있으므로 데이터 로딩을 중단한다.

## 사람 라벨 결합

브라우저 특징 CSV와 사람이 검토한 구간 CSV를 결합한다. 구간 CSV 열은 다음과 같다.

```text
subject_id,session_id,start_ms,end_ms,label,annotator_id,labeling_protocol
```

```powershell
.\.venv\Scripts\python.exe ai\prepare_browser_dataset_v2.py `
  --features C:\data\focusai-v2-features.csv `
  --labels C:\data\focusai-v2-label-intervals.csv `
  --output C:\data\focusai-v2-training.csv `
  --quality-output C:\data\focusai-v2-input-quality.csv
```

겹치는 구간은 거부한다. `unknown` 구간은 `--quality-output`을 지정한 경우에만 별도 신호 품질 CSV로 보존하고 ML 학습 CSV에서는 제외한다. 미라벨 프레임을 제외하려면 `--drop-unlabeled`를 명시한다.

## 후보 학습과 export

훈련 전용 의존성은 Worker 환경과 분리한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r ai\browser_ml\requirements-training.txt
```

```powershell
.\.venv\Scripts\python.exe ai\train_browser_model_v2.py `
  --dataset C:\data\focusai-v2-training.csv `
  --label-source focusai-human-v2 `
  --baseline-metrics C:\data\same-split-baseline-metrics.json
```

비교 후보는 Logistic Regression, Random Forest, Gradient Boosting이다. 모두 scikit-learn → ONNX 변환 경로가 있는 모델로 한정한다. 무작위 프레임 분할은 사용하지 않는다. 서로 다른 피험자로 Train/Validation/Test를 만들고, 후보 선택은 Validation에서만 수행한 뒤 최종 수치는 Test에서 한 번 계산한다. Leave-One-Subject-Out 결과도 별도로 기록한다.

기본 출력은 `ai/browser_ml/artifacts/candidates/<UTC run id>/`이며 다음 파일을 만든다.

```text
focus-state-v2.candidate.onnx       브라우저 후보 artifact
focus-state-v2.metadata.json        schema/order/classes/normalization/version/hash
focus-state-v2.offline.pkl          재현용 offline artifact (production 사용 금지)
metrics.json                        후보별 validation + 선택 모델 test/LOSO
dataset-report.json                 subject/session/source/environment 분포
promotion.json                      정량 승격 게이트 결과
```

도구는 `frontend/public/**`와 `ai/models/**`를 후보 출력 경로로 거부한다. 기존 `frontend/public/focus_classifier.onnx`는 자동으로 교체하지 않는다.

## 승격 조건

후보는 아래 조건을 모두 통과하기 전까지 `candidate_not_active`다.

- 피험자 일반화 검증 가능
- macro F1 ≥ 0.70, balanced accuracy ≥ 0.70
- 모든 클래스 F1 ≥ 0.50, support ≥ 10
- 같은 피험자 분할의 baseline 대비 macro F1/balanced accuracy 하락 ≤ 0.01
- 클래스별 F1 하락 ≤ 0.05
- 실제 브라우저 ONNX 로더/출력 회귀 검증 완료

학습/export CLI는 브라우저 검증을 스스로 통과시킬 수 없으며 항상 해당 항목을 pending으로 기록한다. 별도 승격 절차가 후보 ONNX의 SHA-256에 결합된 브라우저 검증 보고서를 확인해야 한다.

현재 v1의 0/1 규칙 pseudo-label 성능은 v2와 특징·클래스 계약이 달라 자동 baseline으로 간주하지 않는다.

Baseline 파일은 후보와 동일한 test 피험자를 사용했음을 확인할 수 있게 아래 형태여야 한다. `split.test_subjects`가 후보 분할과 다르면 학습 도구가 중단된다.

```json
{
  "metrics": {
    "macro_f1": 0.75,
    "balanced_accuracy": 0.74,
    "per_class": {
      "drowsy": {"f1": 0.70},
      "focus": {"f1": 0.85},
      "gaze_down": {"f1": 0.70},
      "gaze_side": {"f1": 0.75}
    }
  },
  "split": {"test_subjects": ["SUBJECT_005"]}
}
```

## 코드 분류

- 현재 production: `frontend/src/pages/study-session.tsx`, `frontend/src/ai/**`, `frontend/public/focus_classifier.onnx`
- offline 개발: `ai/browser_ml/**`, `ai/prepare_browser_dataset_v2.py`, `ai/train_browser_model_v2.py`
- legacy/production 미사용: `ai/worker.py`, `ai/s3_db_worker.py`, `ai/run_codex_review_worker.py`, 과거 Python inference/변환 파일. 이번 작업에서 삭제하거나 production 의존성으로 연결하지 않는다.

## 기존 영상과 라벨을 재활용하는 통합 실행

이 경로는 Python 3.12와 `numpy<2`가 필요하다. 프로젝트의 production Worker 환경과 분리된 가상 환경에서 다음 의존성을 설치한다.

```powershell
python -m pip install -r ai\browser_ml\requirements-legacy-v2.txt
```

실행 디렉터리는 매번 새 경로여야 한다. 기존 경로가 있으면 도구가 덮어쓰지 않고 중단한다. `--video-root`는 여러 번 지정할 수 있다.

```powershell
python -m ai.build_legacy_v2_candidate `
  --project-root C:\Projects\졸작우승기원\- `
  --output-dir C:\Projects\졸작우승기원\-\ai\browser_ml\artifacts\legacy-v2\20260807T120000 `
  --video-root C:\Projects\졸작우승기원\-\ai\tmp `
  --video-root C:\Projects\졸작우승기원\-\ai\downloads `
  --video-root C:\Users\wkdgu\Downloads\AI 분석용 영상_3min_exact `
  --video-root C:\Projects\focusai_training_scenes_2026-07-18 `
  --video-root C:\Projects\focusai_frame_labels_2026-08-02 `
  --human-label-root C:\Projects\focusai_human_labeling `
  --clip-manifest "C:\Users\wkdgu\Downloads\AI 분석용 영상_3min_exact\manifest.csv" `
  --blind-label-root C:\Projects\focusai_blind_labeling_2026-07-22 `
  --frame-label-root C:\Projects\focusai_frame_labels_2026-08-02
```

도구는 모든 영상의 probe 결과와 SHA-256, 라벨 provenance, 영상-라벨 매칭, 1 FPS causal 특징, 원본 녹화 단위 split, 후보별 validation 성능, held-out test 성능, ONNX와 브라우저 호환성 결과를 한 실행 디렉터리에 보존한다. 최종 보고서는 `reports/final-report.json`과 `reports/final-report.md`다. 후보는 `candidates/focus-state-v2/`에만 생성하며 production v1 모델과 metadata의 실행 전후 해시가 같지 않으면 실패한다.
