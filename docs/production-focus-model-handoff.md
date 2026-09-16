# Production Focus Model Release Handoff

팀원에게 모델과 학습 연산을 전달할 때는 [모델·수학·프런트 통합 안내](model-frontend-integration.md)를 먼저 읽어주세요. ONNX 다운로드, Python 학습 소스, 입력 순서/계산식, 프런트 코드 및 알려진 전처리 차이를 한곳에 정리했습니다.

## 현재 반영된 판정 변경 — 먼저 읽어주세요

기존 ONNX 파일은 동일하지만 **브라우저 최종 판정 코드는 수정되었습니다**.

- `gaze_down` 최종 상태는 전면 MediaPipe의 개인 보정 홍채 Y + 머리 숙임 + 2초 지속으로만 생성합니다. ONNX의 gaze_down 예측은 최종 상태로 채택하지 않습니다.
- 세션마다 눈 뜬 정면 샘플 5개로 기준을 계산합니다. 보정 중/얼굴 또는 홍채 신호 불충분 시 unknown을 사용합니다.
- 졸음은 보정 후 10초 눈 감김 또는 모델 졸음 확률 0.65 이상 + 신체 증거 + 5초 지속이 필요합니다. 손 활동 중 고개 숙임만으로는 졸음 확정을 하지 않습니다.
- 얼굴·홍채·머리·어깨는 전면 카메라만 사용합니다. 책상 카메라는 사람 존재·손 활동의 보조 증거입니다.
- `model_state`, `model_confidence`, `mediapipe_state`, `final_state`, `decision_source`는 메모리 내 진단입니다. 서버에는 `t`, 최종 `state`만 전송합니다.
- 모델 해시와 입출력을 검사하며 모델 로드/추론 실패 시 MediaPipe 판정을 계속합니다.
- 핵심 파일: `frontend/src/ai/production-decision.mjs`, 연결 화면: `frontend/src/pages/study-session.tsx`.

**제한:** ONNX 자체는 여전히 16-feature/5-class입니다. 내부 gaze_down 클래스와 입력 feature를 삭제하거나 34-feature 모델로 재학습한 것은 아닙니다. 새 모델은 승격 실패로 연결하지 않았습니다. 임계값은 앞서 validation에서 동결한 설정을 재사용한 초기값이며, 새 production+규칙 조합의 정확도 검증은 완료되지 않았습니다. 아래 과거 평가 수치를 이번 수정본의 성능으로 인용하면 안 됩니다.

## Release decision

This branch intentionally keeps the last verified browser production model from
commit `5c599bff1f59efcc25c36259dcfc464d9bcbd66b`.

- Deploy the model named `focus_classifier.onnx`.
- Do not replace it with the 3-class B model or the practical-hybrid candidate.
- The handoff commit on top of the stable production base adds no database
  migration, schema change, secret change, or server deployment.
- The deployment owner should deploy and smoke-test this branch as one unit.
  Copying only the ONNX file to `main` is not sufficient because the browser
  loader and MediaPipe assets are part of the same runtime path.

## Pull request scope warning

Remote `main` predates the stable browser production integration. Therefore the
pull request from this release branch to `main` shows the existing application
integration history in addition to the browser decision correction and handoff
documents. Review the latest correction separately from that historical scope.

Deployment owners must review the historical application and database-mapping
differences before merging into `main`. Do not generate or run a database
migration from those code differences. If the deployed environment already
runs the browser production integration, deploy this release branch as the
known-good unit instead of copying only the ONNX binary.

## Exact production artifacts

| Purpose | Repository path | Size | SHA-256 |
| --- | --- | ---: | --- |
| Browser ONNX | `frontend/public/focus_classifier.onnx` | 2,170 bytes | `e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f` |
| AI-side ONNX copy | `ai/models/focus_classifier.onnx` | 2,170 bytes | `e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f` |
| Source classifier bundle | `ai/models/state_classifier.pkl` | 2,549 bytes | `912ae7cb25731e1d2a79bfee5f1d96a0d160117767e24b1e36b4714ec9d12a63` |
| Browser face model | `frontend/public/face_landmarker.task` | 3,758,596 bytes | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| Browser pose model | `frontend/public/pose_landmarker.task` | 5,777,746 bytes | `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a` |

The two ONNX copies must continue to have the same SHA-256.

## Runtime contract and known limitations

This is the existing production contract, not the rejected practical-hybrid
candidate contract.

- ONNX input: `float_input`, `tensor(float)`, shape `[N, 16]`; the browser
  supplies one row with shape `[1, 16]`.
- ONNX outputs: `label`, `tensor(string)`, shape `[N]`, and `probabilities`,
  `tensor(float)`, shape `[N, 5]`.
- Feature order: `is_front_camera`, `is_overhead_camera`, `face_seen`,
  `gaze_side`, `gaze_down`, `bad_posture`, `eye_closed`, `blink`,
  `long_eye_closure`, `head_down`, `head_tilt`, `drowsy`, `page_turn`,
  `pen_fidget`, `restless_hand`, `unknown`.
- Model classes: `drowsy`, `focus`, `gaze_down`, `gaze_side`, `unknown`.
- Browser integration: `frontend/src/pages/study-session.tsx` loads the local
  MediaPipe task files and `/focus_classifier.onnx`, builds the 16 inputs, and
  applies `production-decision.mjs` for calibrated, source-separated decisions.
- MediaPipe WASM and ONNX Runtime WASM are currently loaded from jsDelivr, so
  the deployed browser needs outbound access to that CDN unless the team later
  vendors and pins those WASM assets.

Important: this legacy production model includes `gaze_down` as an ONNX class.
Its output is excluded from final gaze_down decisions, which are now generated
only by MediaPipe. The later 34-feature, 3-class model remains unpromoted.

## Why the newer candidates are not selected

The common fixed-test definition used `focus + gaze_side` as the normal set.

- Production normal-to-`drowsy`: 9 false positives, FPR `0.00308642`.
- 3-class B normal-to-`drowsy`: 1,731 false positives, FPR `0.593621`.
- Practical-hybrid candidate normal-to-`drowsy`: 13 false positives, FPR
  `0.00445816`.
- The practical-hybrid candidate also missed its required `drowsy` precision
  (`0.580645`, required `>= 0.80`) and prediction-concentration gate.

The practical-hybrid candidate SHA-256
`9a37622ae66a86c683b1ae197dac02710c13d178eb886c169edb6a4908fe6342`
and 3-class B SHA-256
`540ecfed7bc757011563fb0f1f028a350d7d80065d665dd1f0c9302fe3f6d140`
must not replace the production model in this release.

## Database boundary

The browser keeps model confidence and decision diagnostics in memory while the
session runs. The stable timeline endpoint creates `AnalysisTimeline` rows
using only `session_id`, `t`, and final `state`. The handoff commit adds no table
or column and does not persist ONNX files, landmarks, feature vectors,
per-second model probabilities, or decision sources in the database. Because
remote `main` is older, its database mappings must be compared with the target
server before the historical integration is merged; this release does not
authorize a migration.

## Reproducible verification

Run from the repository root with Python 3.12 and Node.js installed:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r ai\requirements.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s ai\tests
node --test frontend/src/ai/production-decision.test.mjs frontend/src/ai/production-model.test.mjs

Set-Location frontend
npm ci
npm run build
Set-Location ..

Get-FileHash -Algorithm SHA256 frontend\public\focus_classifier.onnx
Get-FileHash -Algorithm SHA256 ai\models\focus_classifier.onnx
```

Expected repository checks:

- AI unit tests: 109 tests, 0 failures.
- Frontend production build: success. A pre-existing large-chunk warning may
  be printed.
- Both production ONNX hashes equal
  `e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f`.

## Deployment-owner smoke test

1. Build and serve the frontend from this branch.
2. Open the study-session page and grant access to both cameras.
3. Confirm MediaPipe loads and no model-unavailable warning is shown.
4. Start a session, look straight ahead with eyes open for calibration, then
   confirm the displayed state updates. Test sustained downward gaze, eye
   closure, front-face occlusion and ONNX load failure as separate scenarios.
5. Stop the session and verify that `analysis_timeline` contains only the
   existing final `state` values for the session.
6. Confirm that no database migration was executed and no environment secret
   was committed.

Browser camera smoke testing and server deployment were intentionally not run
by the author of this release branch; they remain deployment-owner checks.
