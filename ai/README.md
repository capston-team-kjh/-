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

실패가 발생하면 worker는 해당 SQS 메시지를 삭제하지 않는다. RDS 환경변수가 없거나 placeholder이면 명확한 에러를 남기고 저장을 중단한다.
