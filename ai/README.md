# AI worker

`ai/worker.py`는 SQS 메시지를 받아 S3 영상을 다운로드하고 기존 AI 분석을 실행한다. 기본 결과 저장 방식은 백엔드 API POST가 아니라 RDS 직접 저장이다.

실제 AWS/RDS 값은 아직 코드나 `.env.example`에 넣지 않는다. 운영 값은 나중에 `.env` 또는 OS 환경변수로 주입한다.

## 로컬 수동 분석

```terminal
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r ai\requirements.txt

$env:SAMPLING_FPS="1"
.\.venv\Scripts\python.exe ai\run_local.py --session-id LOCAL_TEST_001 --video "C:\path\to\video.mp4" --camera-type front --mode absent --out output.json
```

`--camera-type`은 `front`, `overhead`, `merged` 중 하나를 사용할 수 있다.

## 환경변수

`.env.example`에는 placeholder만 둔다. 실제 실행 시에는 `.env` 또는 OS 환경변수에 실제 값을 설정한다.

```terminal
AWS_ACCESS_KEY_ID=키
AWS_SECRET_ACCESS_KEY=키
AWS_REGION=ap-northeast-2
SQS_QUEUE_URL=주소
S3_DOWNLOAD_DIR=/tmp/videos
AI_CHUNK_RESULT_DIR=ai/tmp
SAMPLING_FPS=1
RESULT_SINK=rds

RDS_HOST=DB주소
RDS_PORT=3306
RDS_USER=아이디
RDS_PASSWORD=비밀번호
RDS_DATABASE=DB이름
ANALYSIS_RESULT_TABLE=analysis_summary
ANALYSIS_FEEDBACK_TABLE=analysis_feedback
```

`RESULT_SINK` 기본값은 `rds`이다. 기존 백엔드 POST 방식이 필요하면 `RESULT_SINK=post`와 `BACKEND_RESULT_API_URL`을 설정한다.

## worker 실행

```terminal
.\.venv\Scripts\python.exe ai\worker.py
```

한 번만 polling해서 확인할 때:

```terminal
.\.venv\Scripts\python.exe ai\worker.py --once
```

로컬 sample message 파일로 SQS 없이 처리 흐름을 확인할 때:

```terminal
.\.venv\Scripts\python.exe ai\worker.py --sample-message ai\sample_messages\chunk_1.json
.\.venv\Scripts\python.exe ai\worker.py --sample-message ai\sample_messages\chunk_2.json
.\.venv\Scripts\python.exe ai\worker.py --sample-message ai\sample_messages\chunk_3_final.json
```

sample message 모드는 실제 SQS delete를 호출하지 않는다. 단, 메시지의 S3 객체 다운로드와 분석은 일반 worker 흐름과 동일하게 실행된다.

## SQS 메시지 형식

필수 필드는 `session_id`, `user_id`, `s3_bucket`, `s3_key`, `camera_type`, `mode`, `chunk_index`, `is_final_chunk`이다. 하나라도 없으면 실패 로그를 남기고 SQS 메시지는 삭제하지 않는다.

`camera_type`은 `front`, `overhead`, `merged` 중 하나이다. `mode`는 `absent`, `dummy`, `focus_analysis` 중 하나이며, `focus_analysis`는 기존 실제 분석 흐름으로 처리한다.

```json
{
  "session_id": 12,
  "user_id": 3,
  "s3_bucket": "버킷명",
  "s3_key": "uploads/session_12/chunk_1.webm",
  "camera_type": "merged",
  "mode": "focus_analysis",
  "chunk_index": 1,
  "is_final_chunk": false
}
```

마지막 chunk 예시:

```json
{
  "session_id": 12,
  "user_id": 3,
  "s3_bucket": "버킷명",
  "s3_key": "uploads/session_12/chunk_3.webm",
  "camera_type": "merged",
  "mode": "focus_analysis",
  "chunk_index": 3,
  "is_final_chunk": true
}
```

## chunk 처리 방식

SQS 메시지 하나는 1시간 단위 영상 chunk 하나를 의미한다. worker는 S3에서 영상을 다운로드하고 분석한 뒤 chunk 결과를 `AI_CHUNK_RESULT_DIR` 아래에 임시 JSON으로 저장한다.

예:

```terminal
ai/tmp/session_12/chunk_1_result.json
```

`is_final_chunk=false`이면 chunk 결과 JSON 저장 성공 시 SQS 메시지를 삭제하고, DB에는 저장하지 않는다.

`is_final_chunk=true`이면 마지막 chunk 결과까지 저장한 뒤 같은 `session_id`의 chunk 결과를 모두 읽고 `chunk_index` 순서로 병합한다. 시간 값과 count 값은 합산하고, `focus_ratio`, `bad_posture_ratio`, `focus_score`는 최종 합산 summary 기준으로 다시 계산한다. timeline과 events는 chunk offset을 더해 하나의 최종 결과로 만든다.

마지막 chunk에서만 최종 결과를 RDS에 저장한다. 같은 `session_id` 결과가 이미 있으면 `INSERT` 중복 대신 `UPDATE`한다. RDS 저장이 성공해야 SQS 메시지를 삭제한다.

## 테스트

```terminal
python -m py_compile ai/worker.py
python -m unittest discover -s ai/tests
```

## Codex 직접 검수 모드

사용자가 Codex를 통해 worker를 시작할 때는 아래 전용 실행 파일을 사용한다.

```terminal
.\.venv\Scripts\python.exe ai\run_codex_review_worker.py
```

이 모드는 OpenAI Vision API를 끄고, 각 chunk의 의심 프레임을 `ai/manual_review_queue`에 보존한다. 최종 결과는 즉시 RDS에 저장하지 않고 Codex 검수가 끝날 때까지 보류한다. SQS 메시지는 대기 결과가 로컬에 안전하게 기록된 후 삭제된다.

대기 결과 확인:

```terminal
.\.venv\Scripts\python.exe ai\codex_review.py list
```

구간 보정 예시(27~63초의 졸음 오탐을 집중으로 변경):

```terminal
.\.venv\Scripts\python.exe ai\codex_review.py apply --session-id 12 --correction 27:63:focus
```

검수 결과를 RDS 또는 설정된 backend sink에 최종 저장:

```terminal
.\.venv\Scripts\python.exe ai\codex_review.py commit --session-id 12
```

Codex가 직접 프레임을 확인하지 않은 상태에서 `commit`하지 않는다.

## OpenAI 프레임 비전 보조 검증

이 기능은 기존 OpenCV/MediaPipe 분석을 대체하지 않는다. 기존 규칙 기반 분석이 먼저 완료된 후, 문제가 큰 구간의 일부 프레임만 OpenAI Responses API로 보내 결과가 대체로 맞는지 보조 검증한다. 전체 영상 파일은 OpenAI에 업로드하지 않는다.

- 프레임 추출과 JPEG 임시 파일 생성은 로컬 OpenCV에서 수행되므로 이 단계에는 OpenAI 비용이 없다.
- 임시 프레임은 검증 성공·실패 여부와 관계없이 처리 직후 삭제된다.
- 비용은 영상 길이 자체보다 API로 전송한 프레임 수, 이미지 `detail`, 모델, 출력 토큰 수에 좌우된다.
- 10분 영상의 권장 모드는 약 20프레임, 촘촘한 모드는 약 60프레임이다.
- `OPENAI_VISION_ENABLED=false`인 기본 상태에서는 API를 호출하지 않으므로 비용은 0달러다.
- 결과는 기존 `summary`, `timeline`, `events`를 유지한 채 `vision_validation` 필드에 추가된다.
- 비전 판단은 정지 프레임 기반 보조 판단이다. 특히 눈 감김, 짧은 시선 변화, 졸음은 연속 영상보다 오판 가능성이 높다.

### 모델 선택과 비용

2026-06-27 공식 문서 기준 기본값은 `gpt-5.4-nano`다. OpenAI가 최신 비용·속도 중심 작업의 시작점으로 안내하는 모델이고, 이미지 입력과 Responses API, Structured Outputs를 지원한다. 이 작업은 복잡한 생성보다 프레임 분류·대조에 가까워 nano가 적합하다.

`gpt-5.4-mini`는 더 강한 판단이 필요할 때의 품질 우선 대안이지만 입력/출력 단가가 높다. `gpt-5-nano`는 계산상 더 저렴하지만 OpenAI는 새로운 비용 민감 작업에 최신 `gpt-5.4-nano`부터 시작할 것을 권장한다. `gpt-4o-mini`도 사용할 수 있으나, `low` 이미지 1장당 2,833 입력 토큰을 사용해 이 프레임 검증에서는 최신 nano보다 비싸다.

기본 `gpt-5.4-nano`, `detail=low`, 최대 출력 800토큰 가정의 상한성 사전 추정치는 다음과 같다. 프롬프트 텍스트 입력과 실제 출력 토큰 사용량에 따라 청구액은 조금 달라질 수 있다.

| 모드 | 프레임 | 추정 이미지 입력 토큰 | 추정 최대 비용(USD) |
|---|---:|---:|---:|
| recommended | 20 | 12,600 | 약 `$0.00352` |
| dense | 60 | 37,800 | 약 `$0.00856` |

비교로 `gpt-4o-mini`는 같은 조건에서 20프레임 약 `$0.008979`, 60프레임 약 `$0.025977`로 추정된다. 모델 가격과 이미지 토큰 계산 규칙은 바뀔 수 있으므로 배포 전 [OpenAI 모델 가격](https://developers.openai.com/api/docs/models)과 [이미지·비전 비용 계산 문서](https://developers.openai.com/api/docs/guides/images-vision)를 반드시 다시 확인한다. 코드의 단가표는 `ai/focus_ai/vision/cost_estimator.py`에 모아 두었다.

### 환경변수

안전한 기본 설정은 기능 비활성화와 dry-run이다.

```dotenv
OPENAI_VISION_ENABLED=false
OPENAI_VISION_DRY_RUN=true
OPENAI_API_KEY=
OPENAI_VISION_MODEL=
OPENAI_VISION_DETAIL=low
OPENAI_VISION_FRAME_MODE=recommended
OPENAI_VISION_RECOMMENDED_FRAMES=20
OPENAI_VISION_DENSE_FRAMES=60
OPENAI_VISION_APPLY_CORRECTION=false
OPENAI_VISION_MAX_OUTPUT_TOKENS=800
OPENAI_VISION_TIMEOUT_SECONDS=60
```

`OPENAI_VISION_MODEL`을 비워 두면 `gpt-5.4-nano`를 사용한다. 실제 API 호출은 아래 세 조건이 모두 충족될 때만 발생한다.

1. `OPENAI_VISION_ENABLED=true`
2. `OPENAI_VISION_DRY_RUN=false`
3. `OPENAI_API_KEY`에 유효한 키 설정

키가 없으면 자동으로 dry-run으로 전환한다. API 키는 코드에 쓰거나 GitHub에 올리면 안 된다. 저장소의 `.gitignore`에는 `.env`와 `.env.local`이 포함되어 있으며, 실제 키는 이 파일 또는 배포 환경의 secret으로만 관리한다.

`OPENAI_VISION_APPLY_CORRECTION=false`에서는 비전 결과가 점수를 바꾸지 않는다. `true`일 때만 신뢰도 0.75 이상의 명시적 충돌을 해당 타임라인 초에 보수적으로 반영하고 점수를 다시 계산한다. 졸업작품 검증 단계에서는 먼저 `false`로 결과를 비교하는 편이 안전하다.

### dry-run 및 로컬 테스트

저장소 루트에서 다음 명령을 실행하면 실제 API 호출 없이 20/60프레임 비용을 모두 출력하고, 선택한 모드의 로컬 프레임 추출까지 검사한다.

```terminal
python -m ai.focus_ai.vision.test_vision_validation --video "sample.mp4" --dry-run
python -m ai.focus_ai.vision.test_vision_validation --video "sample.mp4" --frame-mode dense --dry-run
```

기존 분석 결과 JSON을 기준으로 문제 구간 우선 추출을 시험하려면 다음처럼 실행한다.

```terminal
python -m ai.focus_ai.vision.test_vision_validation --video "sample.mp4" --analysis-json "output.json" --dry-run
```

실제 호출은 환경변수를 모두 설정한 뒤 명시적으로 `--live`를 사용한다. API 실패, timeout, rate limit, 네트워크 오류는 `vision_validation.error`와 로그에 구분해서 남기며 기존 규칙 기반 분석 결과는 그대로 반환한다.

### 팀에 공유할 운영값

1. 사용할 OpenAI 모델명
2. 세션당 전송할 프레임 수(20 또는 60)
3. 예상 세션 수
4. 세션당 및 전체 예상 비용
5. 비전 보정 결과를 점수에 반영할지 여부
6. API 키 관리 담당자와 secret 저장 위치
7. API 실패 시 기존 규칙 기반 결과만 사용할지 여부(현재 구현은 사용)

실패가 발생하면 worker는 해당 SQS 메시지를 삭제하지 않는다. RDS 환경변수가 없거나 placeholder이면 명확한 에러를 남기고 저장을 중단한다.
