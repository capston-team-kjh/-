# Production Focus Model Release Handoff

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
integration history in addition to this handoff document. The release handoff
commit itself changes only `README.md` and this document.

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
  applies the existing rule fallback.
- MediaPipe WASM and ONNX Runtime WASM are currently loaded from jsDelivr, so
  the deployed browser needs outbound access to that CDN unless the team later
  vendors and pins those WASM assets.

Important: this legacy production model includes `gaze_down` as an ONNX class.
It does not implement the later 34-feature, 3-class, MediaPipe-only
`gaze_down` design. This difference is accepted for this release because the
new candidate did not pass its promotion gates.

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
3. Confirm the browser console reports that four MediaPipe models and the ONNX
   model loaded.
4. Start a session and confirm that the displayed state updates once per
   second.
5. Stop the session and verify that `analysis_timeline` contains only the
   existing final `state` values for the session.
6. Confirm that no database migration was executed and no environment secret
   was committed.

Browser camera smoke testing and server deployment were intentionally not run
by the author of this release branch; they remain deployment-owner checks.
