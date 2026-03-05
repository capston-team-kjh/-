# backend/models.py
import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# Initialize db here, but don't attach it to the app yet
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'USER'
    user_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class StudySession(db.Model):
    __tablename__ = 'STUDY_SESSION'
    session_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())) # CHAR(36) PK
    user_id = db.Column(db.String(36), db.ForeignKey('USER.user_id'), nullable=False) # FK to User
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 학습 시작 시각
    end_time = db.Column(db.DateTime, nullable=True) # 학습 종료 시각 (진행 중이면 NULL)
    status = db.Column(db.String(20), nullable=False, default='READY') # READY/RUNNING/DONE 등
    device = db.Column(db.String(20), nullable=False, default='WEB') # WEB/APP 등
    camera_mode = db.Column(db.String(30), nullable=False, default='front_top') # front_top 등
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 생성 시각

class AnalysisResult(db.Model):
    __tablename__ = 'ANALYSIS_RESULT'
    result_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())) # 결과 ID(UUID)
    session_id = db.Column(db.String(36), db.ForeignKey('STUDY_SESSION.session_id'), nullable=False, unique=True) # 1:1 with Session
    focus_score = db.Column(db.Integer, nullable=False) # 집중도 점수(0~100)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 생성 시각

class MetricSummary(db.Model):
    __tablename__ = 'METRIC_SUMMARY'
    result_id = db.Column(db.String(36), db.ForeignKey('ANALYSIS_RESULT.result_id'), primary_key=True) # 1:1 with Result
    total_time_sec = db.Column(db.Integer, nullable=False) # 전체 학습 시간(초)
    focus_time_sec = db.Column(db.Integer, nullable=False) # 집중 시간(초)
    non_focus_time_sec = db.Column(db.Integer, nullable=False) # 비집중 시간(초)
    focus_ratio = db.Column(db.Float, nullable=False) # 집중 비율(0~1)