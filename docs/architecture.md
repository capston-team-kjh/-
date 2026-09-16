# FocusAI Architecture

이 문서는 현재 코드에서 확인한 내용만 기록한다.

## 구성

- Frontend: `frontend/`의 React + Vite 앱. `src/main.tsx` -> `src/App.tsx` -> `src/routes.tsx`로 시작한다.
- Backend: 저장소 루트의 `main.py` FastAPI 앱과 `routers/`, `models.py`, `schemas.py`, `database.py`.
- AI Worker: `ai/worker.py` SQS worker, `ai/run_local.py` 로컬 분석 진입점, `ai/focus_ai/` 분석 코드.
- Database: SQLAlchemy 모델과 worker RDS 저장 코드 기준 MySQL 계열 DB를 사용한다.
- External: S3 업로드와 SQS 큐는 boto3로 호출한다.

## 현재 흐름

1. Frontend는 `frontend/src/pages/study-session.tsx`에서 `POST ${VITE_API_BASE_URL}/sessions/`로 세션을 생성한다.
2. `DualCameraManager`는 두 카메라 영상을 1280x480 canvas로 합치고 `MediaRecorder`로 webm chunk를 만든다.
3. Frontend는 chunk를 `POST ${VITE_API_BASE_URL}/sessions/{session_id}/upload`로 multipart 업로드한다. form 필드는 `file`, `is_final_chunk`, `recorded_duration_ms`이다.
4. Backend `main.py`의 `/api/v1/sessions/{session_id}/upload`는 파일명에서 `user_id`, `chunk_index`를 파싱하고 S3 key를 `uploads/session_{session_id}/chunk_{chunk_index}.webm`로 만든다.
5. Backend는 S3에 파일을 업로드한 뒤 SQS 메시지를 보낸다. 메시지에는 `session_id`, `user_id`, `s3_bucket`, `s3_key`, `camera_type`, `mode`, `chunk_index`, `is_final_chunk`, 선택적으로 `recorded_duration_ms`가 포함된다.
6. Docker AI Worker의 기본 진입점은 `ai/worker.py`이다. worker는 `SQS_QUEUE_URL`에서 메시지를 받고 S3 객체를 `S3_DOWNLOAD_DIR`로 다운로드한다.
7. Worker는 `_run_existing_analysis()`에서 `ai/run_local.py`의 `run_analysis()`를 호출한다. `mode=focus_analysis`는 내부적으로 `absent` 분석 모드로 매핑되고, `camera_type=merged`이면 합본 영상 분석을 수행한다.
8. 각 chunk 결과는 `AI_CHUNK_RESULT_DIR/session_<session_id>/chunk_<chunk_index>_result.json`에 저장된다.
9. `is_final_chunk=false`이면 chunk 저장 성공 후 SQS 메시지를 삭제하고 DB 저장은 하지 않는다.
10. `is_final_chunk=true`이면 같은 session의 chunk 결과를 `chunk_index` 순서로 병합하고 최종 summary, timeline, events, feedback을 만든다.
11. 기본 `RESULT_SINK=rds`에서는 worker가 MySQL/RDS 테이블에 직접 저장한다. `RESULT_SINK=post`이면 `BACKEND_RESULT_API_URL`로 HTTP POST를 보낸다.
12. 분석과 최종 저장 또는 전송이 모두 성공한 경우에만 SQS 메시지를 삭제한다.

## 확인 필요

- 사용자 요구사항은 1시간 단위 영상 chunk이지만, 현재 `frontend/src/pages/study-session.tsx`의 `SPLICING_INTERVAL_SECONDS`는 300초이다. 실제 운영 chunk 길이는 확인 필요.
- `main.py`에는 SQS URL과 S3 bucket이 코드 상수로 들어 있다. 환경변수화 여부는 확인 필요이며 실제 값은 문서에 기록하지 않는다.
- worker의 HTTP Result API payload는 구현되어 있지만, 현재 FastAPI 라우터에서 이 payload를 받는 전용 Result API 엔드포인트는 확인되지 않았다. 기본 동작은 RDS 직접 저장이다.
- Docker Compose 파일은 현재 루트에서 확인되지 않았다.
