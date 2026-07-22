[Dump20260306.sql](https://github.com/user-attachments/files/25785833/Dump20260306.sql)# 🎯 FocusAI 실시간 집중도 측정 시스템 (FocusAI System)(준영이 스타일로 하나 만들었음)

AI 분석 결과와 수동 라벨을 비교하는 성능 평가 방법은 [docs/ai_evaluation.md](docs/ai_evaluation.md)를 참고한다.

**백엔드 API 및 인증 시스템 모듈**

프로젝트의 핵심 인증 시스템, 집중 세션 관리, 그리고 실시간 AI 집중도 로그 저장을 위한 백엔드 기반을 포함

---

## 🚨 시작 전 필수 체크사항 (Pre-requisites)
서버를 실행하기 전에 반드시 아래 설정을 완료해야 함

1. **MySQL 데이터베이스 생성**
   - MySQL Workbench를 열고 아래 명령어를 실행:
     ```sql
     CREATE DATABASE joljak_db DEFAULT CHARACTER SET utf8mb4;
     ```
   - *이 단계를 건너뛰면 FastAPI 서버 실행 시 데이터베이스 연결 에러가 발생.*

2. **환경 설정 (Environment)**
   - Python 버전: 3.9 이상 권장
   - Node.js 버전: v24.x 이상 (LTS) -> Long-Term Support 버전이 제일 안정적인 버전들이라고 함

---

## 🛠️ 설치 및 실행 방법

### 1. 백엔드 (FastAPI / Flask / MySQL)
```terminal
# 1. 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\activate  # (Mac/Linux: source venv/bin/activate)

# 2. 필수 라이브러리 설치 (bcrypt 버전 충돌 방지 포함)
pip install -r requirements.txt

# 3. 서버 실행 (자동으로 데이터베이스 테이블이 생성됩니다)
uvicorn main:app --reload
```

---

## AI worker 최종 시연 실행 방법

현재 AI worker는 `ai/worker.py`가 AWS SQS 메시지를 받아 S3 영상을 다운로드하고, chunk별 분석 결과를 `AI_CHUNK_RESULT_DIR`에 임시 저장한 뒤 마지막 chunk에서만 최종 결과 1개를 RDS에 직접 저장하는 구조다. `RESULT_SINK=rds`가 기본값이며, 기존 백엔드 HTTP POST 방식은 `RESULT_SINK=post`를 설정했을 때만 사용하는 옵션이다.

실제 AWS 키, SQS URL, S3 버킷명, RDS 주소와 비밀번호는 코드나 이미지에 넣지 않고 `.env` 또는 실행 환경변수로 주입한다.

### 1. 로컬 Python 실행

```terminal
cd C:\Projects\졸작우승기원\-
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r ai\requirements.txt
copy .env.example .env
```

`.env`의 placeholder 값을 실제 실행 환경 값으로 바꾼 뒤 worker를 실행한다.

```terminal
.\.venv\Scripts\python.exe ai\worker.py
.\.venv\Scripts\python.exe ai\worker.py --once
```

로컬 파일로 기존 분석만 확인할 때는 다음처럼 실행한다.

```terminal
$env:SAMPLING_FPS="1"
.\.venv\Scripts\python.exe ai\run_local.py --session-id LOCAL_TEST_001 --video "C:\path\to\video.mp4" --camera-type merged --mode focus_analysis --out output.json
```

### 2. Docker build

```terminal
cd C:\Projects\졸작우승기원\-
docker build -t focus-ai-worker .
```

### 3. Docker run

```terminal
docker run --rm --env-file .env focus-ai-worker
docker run --rm --env-file .env focus-ai-worker --once
```

sample message 파일로 실행할 때:

```terminal
docker run --rm --env-file .env focus-ai-worker --sample-message ai/sample_messages/chunk_1.json
docker run --rm --env-file .env focus-ai-worker --sample-message ai/sample_messages/chunk_3_final.json
```

### 4. Docker에서 AWS 인증 주입

`.env`에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`을 넣거나, 로컬 AWS CLI profile을 읽기 전용으로 마운트한다. ECS/EC2에서 실행할 때는 코드에 AWS 키를 넣지 말고 IAM Role을 사용한다.

Windows CMD:

```terminal
docker run --rm --env-file .env -v "%USERPROFILE%\.aws:/root/.aws:ro" -e AWS_PROFILE=default focus-ai-worker
```

PowerShell:

```terminal
docker run --rm --env-file .env -v "$env:USERPROFILE\.aws:/root/.aws:ro" -e AWS_PROFILE=default focus-ai-worker
```

### 5. .env 값

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

`RESULT_SINK=rds`는 마지막 chunk 처리 시 RDS에 직접 저장한다. 예전 백엔드 POST 방식이 필요할 때만 `RESULT_SINK=post`와 `BACKEND_RESULT_API_URL=주소`를 함께 설정한다.

### 6. SQS 메시지 형식

일반 chunk:

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

마지막 chunk:

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

필수 필드는 `session_id`, `user_id`, `s3_bucket`, `s3_key`, `camera_type`, `mode`, `chunk_index`, `is_final_chunk`이다. `camera_type`은 `front`, `overhead`, `merged` 중 하나이고, `mode`는 `absent`, `dummy`, `focus_analysis` 중 하나다.

worker는 non-final chunk에서는 chunk 결과만 저장하고 SQS 메시지를 삭제한다. 마지막 chunk에서는 `chunk_index` 순서의 결과를 합쳐 최종 결과 1개만 RDS에 저장한 뒤 성공 시 SQS 메시지를 삭제한다.

### 7. 검증 명령

```terminal
py -3 -m py_compile ai\worker.py
py -3 -m unittest discover -s ai\tests
docker build -t focus-ai-worker .
docker run --rm --env-file .env focus-ai-worker --once
```

Docker 이미지의 기본 실행 대상은 `ai/worker.py`이고, `--once`, `--sample-message` 같은 CLI 인자는 `docker run` 뒤에 그대로 전달할 수 있다.

### 2. 프론트엔드 ( React + Vite )

---
### 노드 패기지를 터미널로 설치하기 전에 node.js (v24.x LTS) 설치

1. **노드 페이지 방문하고 'Pre-built node.js'로 내려가서 운영체제 선택 이후 installer 설치.**
   - *필수 참고 사항: 설치할때 'Add to PATH' 옵션이 체크되어 있는지 확인하고 설치 실행할 것*
   - https://nodejs.org/en/download

2. **설치 이후, 터미널에서 node와 npm 버전 확인**
   ```terminal
   node -v  # v24.x 확인

   npm -v  # v11.x 확인
   ```
---
### 노드 패키지 설치
```terminal
# 1. 새로운 터미널에서 포론트엔드 다이렉토리로 이동 ( 여기서는 가상 환경 활성화 안함 )
cd frontend

# 2. 노드 패캐지 설치
npm install

# 3. 개발 환경 시작
npm run dev
```
---
### 집중도 분석에 관련된 조건 api 제작
```terminal
# 1. 기존 코드에서 routers 파일 안에 analysis.py로 집중도 분석 이후 나올 값들을 api로 제작했음다

# 2. models.py 46줄 이후와 schemas.py의 75줄 이후의 코드가 추가되었고, main.py에서도 관련된 코드 수정되었습니당
```
 
