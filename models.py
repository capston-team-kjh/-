from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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