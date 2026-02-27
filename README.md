#  집중도 학습 시스템 (Focus Study System)
**학생용 UI 및 인증 시스템 모듈**

프로젝트의 핵심 인증 시스템, 사용자 설정, 그리고 학습 데이터 관리를 위한 백엔드 기반을 포함

---

##  시작 전 필수 체크사항 (Pre-requisites)
서버를 실행하기 전에 반드시 아래 설정을 완료해야 함

1. **MySQL 데이터베이스 생성**
   - MySQL Workbench를 열고 아래 명령어를 실행:
     ```sql
     CREATE DATABASE focus_db;
     ```
   - *이 단계를 건너뛰면 Flask 서버 실행 시 'Database not found' 에러가 발생.*

2. **환경 설정 (Environment)**
   - Node.js 버전: 18.x 이상 권장
   - Python 버전: 3.8 이상 권장

---

## 🛠️ 설치 및 실행 방법

### 1. 백엔드 (Flask & MySQL)
```terminal
cd backend
# 1. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # (Windows: venv\Scripts\activate)

# 2. 필수 라이브러리 일괄 설치
pip install -r requirements.txt

# 3. 서버 실행 (자동으로 테이블이 생성)
flask run --debug ( 테스트 용으로 현재 사용 중 )
```
### 2. 프론트엔드 (React & Vite)
```terminal
cd frontend
# 1. 패키지 설치
npm install

# 2. 실행
npm run dev
