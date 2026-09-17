# AI Worker Harness Rules

- 로컬 분석 진입점은 `ai/run_local.py`이다. worker가 실제로 분석을 호출할 때도 `ai/worker.py`의 `_run_existing_analysis()`가 `run_local.run_analysis()`를 사용한다.
- SQS worker 진입점은 `ai/worker.py`이며 기본 result sink는 `RESULT_SINK=rds`이다. HTTP 전송은 `RESULT_SINK=post`와 `BACKEND_RESULT_API_URL`이 설정된 경우에만 사용한다.
- `ai/focus_ai/analyze.py`, `ai/analyzer/focus_score.py`의 상태 판정과 점수 계산식을 요청 없이 변경하지 않는다.
- Python은 3.12 기준으로 검증한다. `numpy<2` 호환성을 유지한다.
- OpenAI Vision 기본 안전값은 `OPENAI_VISION_ENABLED=false`, `OPENAI_VISION_DRY_RUN=true`, `OPENAI_API_KEY=` 빈 값, `OPENAI_VISION_APPLY_CORRECTION=false`이다.
- SQS 메시지는 분석, chunk 저장, 최종 결과 저장 또는 전송이 모두 성공한 경우에만 삭제한다. 실패 경로 테스트를 추가하거나 유지한다.
- AI 테스트는 저장소 루트에서 다음 명령으로 실행한다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s ai\tests
```
