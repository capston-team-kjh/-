from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy.orm import Session
from passlib.hash import bcrypt
from models import User, FocusSession, FocusLog
from database import SessionLocal, engine 
from datetime import datetime
import uuid
import random
import bcrypt

app = Flask(__name__)
CORS(app)

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

@app.route('/api/users/me', methods=['GET'])
def get_user_profile():
    user_id = request.headers.get('X-User-Id') 
    
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    # Query the root User model using the ID from FastAPI login
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.strftime("%Y-%m-%d")
    }), 200

@app.route('/api/users/me/password', methods=['PATCH'])
def update_password():
    user_id = request.headers.get('X-User-Id')
    data = request.json
    current_pw = data.get('current_password')
    new_pw = data.get('new_password')

    db = get_db()
    user = db.query(User).filter(User.id == user_id).first()

    # Use passlib to verify so it's compatible with teammate's login
    if not user or not bcrypt.verify(current_pw, user.password_hash):
        return jsonify({"message": "현재 비밀번호가 일치하지 않습니다."}), 401

    # Hash new password using the same method as FastAPI
    user.password_hash = bcrypt.hash(new_pw)
    db.commit()

    return jsonify({"result": "ok"}), 200

@app.route('/api/results/recent', methods=['GET'])
def get_recent_results():
    # Frontend should now pass user_id (e.g., from a header after FastAPI login)
    user_id = request.headers.get('X-User-Id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    size = request.args.get('size', 5, type=int)
    db = get_db()

    # Query: Get the most recent sessions for this user
    # We join FocusSession with FocusLog to calculate stats
    sessions = db.query(FocusSession).filter(
        FocusSession.user_id == user_id
    ).order_by(FocusSession.start_time.desc()).limit(size).all()

    items = []
    for s in sessions:
        duration_min = 0
        if s.end_time:
            duration_min = int((s.end_time - s.start_time).total_seconds() / 60)
            
        # Get average score from the logs associated with this session
        avg_score = db.query(func.avg(FocusLog.focus_score)).filter(
            FocusLog.session_id == s.id
        ).scalar() or 0

        items.append({
            "session_id": s.id,
            "date": s.start_time.strftime("%Y-%m-%d"),
            "start_time": s.start_time.strftime("%H:%M"),
            "duration_min": duration_min,
            "focus_score": round(float(avg_score), 1),
            "status": s.status
        })

    return jsonify({"items": items}), 200

# 1. Daily Summary API
@app.route('/api/dashboard/daily', methods=['GET'])
def get_daily_summary():
    user_id = request.headers.get('X-User-Id')
    target_date_str = request.args.get('date') # YYYY-MM-DD
    
    db = get_db()
    
    # Calculate stats for the specific day
    # We sum the duration of completed sessions and average the scores of all logs
    stats = db.query(
        func.count(FocusSession.id).label('count'),
        func.avg(FocusLog.focus_score).label('avg_score')
    ).join(FocusLog, FocusSession.id == FocusLog.session_id)\
     .filter(FocusSession.user_id == user_id)\
     .filter(func.date(FocusSession.start_time) == target_date_str).first()

    return jsonify({
        "date": target_date_str,
        "avg_focus_score": round(float(stats.avg_score or 0), 1),
        "session_count": stats.count or 0
    }), 200

# 2. Weekly/Monthly Summary API
@app.route('/api/dashboard/summary', methods=['GET'])
def get_range_summary():
    user_id = request.headers.get('X-User-Id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    range_type = request.args.get('range', 'weekly') 
    days_to_subtract = 7 if range_type == 'weekly' else 30
    start_date = datetime.now() - timedelta(days=days_to_subtract)

    db = get_db()

    # Query: Total study time (sum of differences between start and end)
    # and average focus score from all logs in that period
    stats = db.query(
        func.count(func.distinct(func.date(FocusSession.start_time))).label('active_days'),
        func.avg(FocusLog.focus_score).label('avg_score')
    ).join(FocusLog, FocusSession.id == FocusLog.session_id)\
     .filter(FocusSession.user_id == user_id)\
     .filter(FocusSession.start_time >= start_date).first()

    return jsonify({
        "range": range_type,
        "avg_focus_score": round(float(stats.avg_score or 0), 1),
        "active_days": stats.active_days or 0
    }), 200

@app.route('/api/results/<int:session_id>', methods=['GET', 'DELETE'])
def handle_session_detail(session_id):
    user_id = request.headers.get('X-User-Id')
    db = get_db()

    session = db.query(FocusSession).filter(
        FocusSession.id == session_id, 
        FocusSession.user_id == user_id
    ).first()

    if not session:
        return jsonify({"message": "세션을 찾을 수 없습니다."}), 404

    if request.method == 'DELETE':
        db.delete(session) # Cascade will handle FocusLogs if set up in models.py
        db.commit()
        return jsonify({"deleted": True}), 200

    # GET: Aggregate data from FocusLogs for this session
    logs = db.query(FocusLog).filter(FocusLog.session_id == session_id).all()
    
    # Simple timeline generation for the frontend
    timeline = [{"time": l.timestamp.strftime("%H:%M"), "score": l.focus_score} for l in logs]

    return jsonify({
        "session_id": session.id,
        "start_time": session.start_time.strftime("%Y-%m-%d %H:%M"),
        "status": session.status,
        "timeline": timeline
    }), 200

@app.route('/api/results', methods=['GET'])
def get_all_results():
    user_id = request.headers.get('X-User-Id')
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 10, type=int)

    db = get_db()

    # Query sessions and calculate average score for each on the fly
    query = db.query(
        FocusSession,
        func.avg(FocusLog.focus_score).label('avg_score')
    ).join(FocusLog, FocusSession.id == FocusLog.session_id)\
     .filter(FocusSession.user_id == user_id)\
     .group_by(FocusSession.id)\
     .order_by(FocusSession.start_time.desc())

    # Manual pagination calculation since we aren't using Flask-SQLAlchemy's helper
    total = query.count()
    sessions = query.offset((page - 1) * size).limit(size).all()

    items = []
    for s, avg_score in sessions:
        duration_min = 0
        if s.end_time:
            duration_min = int((s.end_time - s.start_time).total_seconds() / 60)
            
        items.append({
            "session_id": s.id,
            "date": s.start_time.strftime("%Y-%m-%d"),
            "time": s.start_time.strftime("%H:%M"),
            "duration": f"{duration_min}m",
            "score": round(float(avg_score or 0), 1),
            "status": s.status
        })

    return jsonify({
        "items": items,
        "page": page,
        "size": size,
        "total": total
    }), 200