# 브라우저 판정 수정 계획 및 범위

- 기존 production ONNX의 바이트와 16-feature 입력 계약을 보존한다.
- 얼굴·홍채·눈·머리는 전면 카메라만 사용한다. 책상 카메라는 사람 존재와 손 활동 보조 증거로만 사용한다.
- 세션마다 정면·눈 뜬 상태에서 개인 기준값을 계산한다. 보정 전이나 얼굴 신호가 없으면 졸음을 확정하지 않는다.
- 최종 gaze_down은 보정된 홍채 Y와 머리 숙임이 연속 유지될 때만 MediaPipe가 생성한다. ONNX gaze_down 출력은 진단에만 남긴다.
- 졸음은 장기 눈 감김 안전 규칙 또는 모델 확률·눈 감김/머리 숙임·연속 지속의 결합으로 생성한다.
- 모델/MediaPipe/최종 상태와 출처는 메모리에 분리하고 API에는 t/state만 보낸다.
- production 해시와 입출력 계약을 확인한다. 로드 실패 시 MediaPipe 경로를 계속 사용한다.
- 기존 validation에서 동결했던 임계값을 초기 설정으로 재사용한다. 기존 고정 test를 보고 조정하지 않는다. 새 production+규칙 조합의 정확도가 검증되었다고 주장하지 않는다.
- 회귀 테스트: 모델 gaze_down 차단, MediaPipe gaze_down 지속, 보정/얼굴 누락, 졸음 지속, 입력 오류, 시간 단절, 보조 행동, 저장 필드 제한.
- 검증 후 기존 release 브랜치와 PR #10을 갱신한다. 새 34-feature/3-class 모델 승격과 서버 배포는 포함하지 않는다.

## 검증 결과 (2026-09-16)

- `node --test frontend/src/ai/production-decision.test.mjs frontend/src/ai/production-model.test.mjs`: 16/16 통과. 실제 ONNX Runtime Web WASM으로 모델 해시, 출력 dtype/shape 및 클래스 순서를 확인했다.
- `./scripts/verify.ps1`: PASS=10, FAIL=0, SKIP=4. AI 테스트 109개와 Python 문법 검사, 프런트엔드 빌드 통과. Docker 관련 검증 등 환경상 생략 항목은 스크립트 결과 기준이다.
- `npm --prefix frontend run build`: 마지막 카메라 신선도 수정 후 재통과. 기존 번들 크기 경고는 남아 있다.
- `git diff --check`: 통과. production 모델 SHA-256은 변경 전후 `e07aabc51e7ac1b48610ebd3eba25bd671297d1a4b25a48c1ba379f4f125577f`로 동일하다.
- 멈춘 전면 영상은 얼굴 증거로 사용하지 않는다. 전면 트랙 상태와 영상 시간 진행 여부를 확인한다.
- 실제 브라우저 카메라/서버 저장 E2E, 로드 실패 UI 재현, 새 조합의 정확도 평가는 실행하지 않았다. 별도 TypeScript 검사 도구는 현재 설치되어 있지 않아 전용 타입 검사는 실행하지 않았다.
- 확률·지속 시간은 이전 후보 설정 재사용이며 눈 감김 비율 0.7은 초기 보정 설정이다. 새 조합의 검증 완료 임계값이라고 해석하면 안 된다.
- 이번 커밋은 backend/DB 및 원본 데이터와 모델을 변경하지 않는다. 다른 학습 worktree의 미커밋 변경도 수정하지 않았다.
