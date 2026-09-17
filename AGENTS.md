# FocusAI Codex 운영 규칙

## AI 서버 시작 요청

사용자가 이 저장소에서 "AI 서버를 켜줘", "worker를 시작해줘"처럼 요청하면 일반 `ai/worker.py` 대신 아래 명령으로 실행한다.

```powershell
.\.venv\Scripts\python.exe ai\run_codex_review_worker.py
```

이 실행은 유료 OpenAI Vision API를 호출하지 않으며 최종 결과를 즉시 RDS에 저장하지 않는다. 모든 최종 세션은 `ai/manual_review_queue/session_<id>/`에 보류된다.

서버를 시작한 Codex 작업자는 사용자가 중지를 요청할 때까지 worker 로그와 검수 대기열을 계속 모니터링한다. 새 영상마다 반드시 다음 절차를 완료한다.

1. `python ai/codex_review.py list`로 새 대기 세션을 찾는다.
2. `review_manifest.json`의 의심 이벤트와 `chunk_*/frames/*.jpg`를 직접 확인한다.
3. 졸음·시선 이탈·자세 불량·자리 비움·인식 불안정이 실제 영상과 일치하는지 판정한다.
4. 오탐 구간은 `python ai/codex_review.py apply --session-id <id> --correction 시작초:종료초:상태`로 수정한다.
5. 수정이 없어도 검수를 완료한 뒤 `python ai/codex_review.py commit --session-id <id>`를 실행한다.
6. RDS의 summary, timeline, events, feedback 행을 다시 조회해 저장 결과를 검증한다.
7. 사용자에게 세션 ID, 최종 점수, 수동 보정 구간을 보고한다.

독서·필기 중 고개를 숙인 상태는 손 움직임과 교재 활동이 이어지면 졸음으로 확정하지 않는다. 실제 졸음은 눈 감김의 지속, 고개 떨굼, 학습 활동 중단을 함께 보고 판단한다.

검수와 커밋이 끝나기 전에는 작업 완료로 보고하지 않는다.

## 프로젝트 구조

- `frontend/`: React + Vite 프론트엔드. `frontend/src/main.tsx`가 진입점이고 `frontend/src/pages/study-session.tsx`에서 세션 생성과 영상 chunk 업로드를 호출한다.
- `main.py`, `routers/`, `models.py`, `schemas.py`, `database.py`: FastAPI + MySQL 백엔드. `main.py`가 앱 진입점이다.
- `ai/`: Python AI Worker. 로컬 분석 진입점은 `ai/run_local.py`이고 SQS worker 진입점은 `ai/worker.py`이다.
- `ai/focus_ai/`: OpenCV/MediaPipe 기반 분석 로직과 OpenAI Vision 보조 검증 코드.
- `ai/analyzer/focus_score.py`: 집중도 점수 계산 규칙.
- `docs/`: 아키텍처, API 계약, 분석 규칙 문서.
- `scripts/verify.ps1`: Windows PowerShell 통합 검증 스크립트.

## 실행 명령

### Backend

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
npm run build
```

현재 `frontend/package.json`에는 `lint` script가 없다. lint를 추가하기 전까지 통합 검증은 프론트엔드 lint를 `SKIP`으로 보고해야 한다.

### AI Worker

```powershell
.\.venv\Scripts\python.exe -m pip install -r ai\requirements.txt
.\.venv\Scripts\python.exe ai\run_local.py --session-id LOCAL_TEST_001 --video "C:\path\to\video.mp4" --camera-type merged --mode focus_analysis --out output.json
.\.venv\Scripts\python.exe ai\worker.py --once
```

Docker 실행 대상은 `ai/worker.py`이다.

```powershell
docker build -t focus-ai-worker .
docker run --rm --env-file .env focus-ai-worker --once
```

## 검증 명령

```powershell
.\scripts\verify.ps1
.\.venv\Scripts\python.exe -m unittest discover -s ai\tests
cd frontend
npm run build
```

## 작업 규칙

- 수정 전에 관련 코드와 호출 관계를 확인한다. 특히 Frontend -> Backend upload -> S3/SQS -> AI Worker -> Result sink 흐름을 먼저 따라간다.
- 기존 OpenCV/MediaPipe 분석 로직, 상태 판정 기준, 점수 계산식을 임의로 바꾸지 않는다.
- 요청받지 않은 파일, 기능, UI, API 계약을 수정하지 않는다.
- 변경 후 가능한 테스트와 검증을 실행한다. 실행할 수 없는 항목은 `SKIP`과 사유를 보고한다.
- 실패한 테스트를 숨기거나 성공했다고 보고하지 않는다.
- 최종 보고 전에 `git diff`를 직접 검토하고, 제품 기능이나 분석 동작 변경이 섞였는지 확인한다.
- 비밀정보는 환경변수로만 관리한다. `.env`, `.env.local`, 실제 AWS 키, DB 비밀번호, API 키의 값을 읽거나 출력하지 않는다.
- `.env`와 `.env.local`은 반드시 gitignore 상태로 유지한다.
