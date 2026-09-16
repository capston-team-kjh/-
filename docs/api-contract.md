# API Contract

이 문서는 현재 코드 기준의 계약이다.

## Frontend -> Backend Upload API

Endpoint: `POST /api/v1/sessions/{session_id}/upload`

Content-Type: `multipart/form-data`

필수:

- `file`: webm chunk 파일. 현재 프론트엔드는 `user_{user_id}_session_{session_id}_part{chunk_index}.webm` 형식으로 보낸다.

선택:

- `is_final_chunk`: 문자열. `"true"`이면 마지막 chunk로 처리하고 그 외 값은 false로 처리한다. 기본값은 `"false"`.
- `recorded_duration_ms`: 양수 숫자 문자열. 있으면 SQS 메시지에 그대로 포함된다.

Backend 동작:

- 파일명에서 `user_id`, `chunk_index`를 파싱한다. 파싱 실패 시 현재 코드는 `user_id=0`, `chunk_index=1`로 처리한다.
- S3 key는 `uploads/session_{session_id}/chunk_{chunk_index}.webm`이다.
- S3 업로드와 SQS 전송이 성공하면 `{"status":"success","queued":true,"is_final_chunk":<bool>}`를 반환한다.
- 실패하면 HTTP 502를 반환한다.

## Backend -> SQS Message

SQS `MessageBody`는 JSON object여야 한다.

필수:

- `session_id`: 문자열 또는 숫자. worker 내부에서는 문자열로 정규화한다.
- `user_id`: 문자열 또는 숫자. worker 내부에서는 문자열로 정규화한다.
- `s3_bucket`: 비어 있지 않은 문자열.
- `s3_key`: 비어 있지 않은 문자열.
- `camera_type`: `front`, `overhead`, `merged` 중 하나.
- `mode`: `absent`, `dummy`, `focus_analysis` 중 하나.
- `chunk_index`: 0 이상의 정수.
- `is_final_chunk`: boolean 또는 boolean으로 파싱 가능한 값.

선택:

- `recorded_duration_sec`: 양수 숫자.
- `recorded_duration_ms`: 양수 숫자. worker는 초 단위로 변환한다.

오류 처리:

- `Body`가 비어 있거나 JSON object가 아니면 `MessageValidationError`.
- 필수 필드가 누락되거나 빈 문자열이면 `MessageValidationError`.
- `camera_type`, `mode`, `chunk_index`, `is_final_chunk`, 녹화 길이 값이 유효하지 않으면 `MessageValidationError`.
- worker poll loop는 처리 중 예외가 발생하면 로그를 남기고 SQS 메시지를 삭제하지 않는다.
- SQS 메시지는 분석, chunk 결과 저장, 최종 결과 저장 또는 HTTP 전송이 모두 성공한 경우에만 삭제한다.

예시:

```json
{
  "session_id": 12,
  "user_id": 3,
  "s3_bucket": "bucket-name",
  "s3_key": "uploads/session_12/chunk_1.webm",
  "camera_type": "merged",
  "mode": "focus_analysis",
  "chunk_index": 1,
  "is_final_chunk": false,
  "recorded_duration_ms": 300000
}
```

## AI Worker Result

`ai/run_local.py`와 `ai/worker.py`의 분석 결과 object 주요 필드:

필수로 기대되는 필드:

- `session_id`
- `status`: `success` 또는 `failed`
- `meta`: 분석 메타데이터. 예: `camera_type`, `duration_sec`, `processing_time_sec`, `version`, `warnings`
- `summary`: 상태별 시간, 비율, count, `focus_score`, `concentration_score`
- `timeline`: 초 단위 상태 배열. 각 item은 `t`, `state`, `states`, `flags` 등을 포함한다.
- `events`: 상태 이벤트 배열. 각 item은 `type`, `start_sec`, `end_sec`, `score` 등을 포함한다.

선택으로 추가되는 필드:

- `feedback`
- `feedback_evidence`
- `personal_feedback`
- `feedback_source`
- `feedback_version`
- `time_patterns`
- `vision_validation`
- `codex_manual_review`
- `front_result`
- `overhead_result`

## Worker -> Backend Result API Payload

`RESULT_SINK=post`일 때 worker가 `BACKEND_RESULT_API_URL`로 보내는 JSON payload:

필수:

- `session_id`
- `user_id`
- `status`: 현재 `"completed"`
- `focus_score`: 0~100 정수
- `summary`
- `timeline`
- `events`

`summary` 필드:

- `total_time`
- `focus_time`
- `bad_posture_time`
- `gaze_away_time`
- `drowsy_time`
- `absence_time`
- `absence_count`
- `bad_posture_count`
- `gaze_away_count`
- `drowsy_count`

선택 또는 보조 필드:

- `feedback`
- `time_patterns`
- `personal_feedback`
- `feedback_source`
- `feedback_version`
- `feedback_validation`
- `vision_validation`

오류 처리:

- `BACKEND_RESULT_API_URL`이 없으면 worker는 RuntimeError를 발생시키고 SQS 메시지를 삭제하지 않는다.
- HTTP POST는 `BACKEND_POST_TIMEOUT_SECONDS`를 timeout으로 사용한다.
- HTTP 응답이 실패하면 `raise_for_status()`로 예외가 발생하고 SQS 메시지를 삭제하지 않는다.

확인 필요:

- 현재 FastAPI 코드에서 위 worker 최종 payload를 수신하는 전용 Result API endpoint는 확인되지 않았다. 현재 기본 저장 방식은 `RESULT_SINK=rds`를 통한 MySQL/RDS 직접 저장이다.
