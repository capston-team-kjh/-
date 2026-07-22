# Backend Router Harness Rules

- 백엔드 앱 진입점은 저장소 루트의 `main.py`이고 라우터는 `routers/`에서 등록된다.
- `routers/analysis.py`의 `/api/v1/analysis/`는 현재 생체 점수 저장 API이며, worker 최종 결과 payload를 받는 Result API 엔드포인트는 현재 코드에서 확인되지 않았다.
- `main.py`의 `/api/v1/sessions/{session_id}/upload`는 multipart 영상 chunk를 받아 S3 업로드 후 SQS 메시지를 전송한다.
- 실제 AWS, S3, SQS, MySQL 운영 서버에 연결하는 테스트를 작성하지 않는다. 필요한 경우 boto3, DB 세션, HTTP 호출은 mock으로 검증한다.
- DB 접속정보와 AWS 리소스 값은 코드에 추가하지 말고 환경변수로만 주입한다.
