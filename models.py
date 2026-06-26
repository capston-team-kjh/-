from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, BigInteger, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.sql import func
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=func.now())

    # 관계 설정 (한 명의 유저는 여러 개의 세션을 가짐)
    sessions = relationship("FocusSession", back_populates="user", cascade="all, delete-orphan")


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_time = Column(DateTime, nullable=False, default=func.now())
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), default="active") # 상태: active, completed, canceled
    duration_sec = Column(Integer, nullable=True)

    # 관계 설정
    user = relationship("User", back_populates="sessions")
    logs = relationship("FocusLog", back_populates="session", cascade="all, delete-orphan")


class FocusLog(Base):
    __tablename__ = "focus_logs"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("focus_sessions.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    focus_score = Column(Float, nullable=False)
    state = Column(String(50), nullable=False) # 상태: focused, drowsy, away 등

    # 관계 설정
    session = relationship("FocusSession", back_populates="logs")

 # 눈동자, 안면인식, 몸 움직임, 자리이탈
class FocusAnalysis(Base):
    __tablename__ = "focus_analysis"

    id = Column(Integer, primary_key=True, index=True)
    eye_score = Column(Float, nullable=False)
    head_score = Column(Float, nullable=False)
    body_score = Column(Float, nullable=False)
    is_absent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now())


# AI Analysis Models
class AnalysisEvent(Base):
    __tablename__ = "analysis_events"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True) # BIGINT + AI
    session_id = Column(String(100), nullable=False) # VARCHAR(100) NN
    event_type = Column(String(50), nullable=True)   # VARCHAR(50)
    start_sec = Column(Float, nullable=True)         # FLOAT
    end_sec = Column(Float, nullable=True)           # FLOAT
    score = Column(Float, nullable=True)             # FLOAT


class AnalysisFeedback(Base):
    __tablename__ = "analysis_feedback"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True) # BIGINT + AI
    session_id = Column(String(100), nullable=False) # VARCHAR(100) NN
    feedback_text = Column(LONGTEXT, nullable=False)   # LONGTEXT NN (Mapped to String in SQLAlchemy)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now()) # TIMESTAMP with trigger
    personal_feedback = Column(JSON, nullable=True)
    feedback_source = Column(String(30), nullable=True)
    feedback_version = Column(String(30), nullable=True)
    feedback_created_at = Column(DateTime, nullable=True)


class AnalysisSummary(Base):
    __tablename__ = "analysis_summary"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True) # BIGINT + AI
    session_id = Column(String(100), nullable=False) # VARCHAR(100) NN
    focus_ratio = Column(Float, nullable=True)       # FLOAT
    absent_count = Column(Integer, nullable=True)    # INT
    absent_total_sec = Column(Float, nullable=True)  # FLOAT
    away_count = Column(Integer, nullable=True)      # INT
    away_total_sec = Column(Float, nullable=True)    # FLOAT
    bad_posture_ratio = Column(Float, nullable=True) # FLOAT
    processing_time_sec = Column(Float, nullable=True) # FLOAT
    camera_type = Column(String(50), nullable=True)  # VARCHAR(50)
    version = Column(String(50), nullable=True)      # VARCHAR(50)
    analyzed_at = Column(DateTime, default=func.now()) # TIMESTAMP


class AnalysisTimeline(Base):
    __tablename__ = "analysis_timeline"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True) # BIGINT + AI
    session_id = Column(String(100), nullable=False) # VARCHAR(100) NN
    t = Column(Float, nullable=True)                 # FLOAT
    state = Column(String(50), nullable=True)        # VARCHAR(50)