from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy.orm import Session
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
    # 1. Get the Authorization header
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401

    # 2. Extract the actual token string
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token)

    if not user_uuid:
        return jsonify({"error": "Invalid token"}), 401

    # 3. Query MySQL using the UUID retrieved from the token
    user = User.query.filter_by(user_id=user_uuid).first()
    
    return jsonify({
        "email": user.email,
        "created_at": user.created_at.strftime("%Y-%m-%d")
    }), 200

@app.route('/api/users/me/password', methods=['PATCH'])
def update_password():
    # 1. Verify Token first
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"message": "인증 정보가 없습니다."}), 401

    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token) # Look up which UUID owns this token

    if not user_uuid:
        return jsonify({"message": "유효하지 않은 세션입니다."}), 401

    # 2. Process the request data
    data = request.json
    current_pw = data.get('current_password')
    new_pw = data.get('new_password')

    # 3. Find the user in MySQL
    user = User.query.filter_by(user_id=user_uuid).first()

    # 4. Security Check: Verify current password hash
    if not user or not bcrypt.checkpw(current_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
        return jsonify({"message": "현재 비밀번호가 일치하지 않습니다."}), 401

    # 5. Hash new password and save
    user.password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db.session.commit()

    return jsonify({"result": "ok"}), 200

@app.route('/api/results/recent', methods=['GET'])
def get_recent_results():
    # Verify Authorization
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token)
    if not user_uuid:
        return jsonify({"error": "Invalid token"}), 401

    # Query size from parameters (optional, defaults to 5)
    size = request.args.get('size', 5, type=int)

    # Join STUDY_SESSION with ANALYSIS_RESULT to get all required fields
    results = db.session.query(StudySession, AnalysisResult).\
        join(AnalysisResult, StudySession.session_id == AnalysisResult.session_id).\
        filter(StudySession.user_id == user_uuid).\
        order_by(StudySession.start_time.desc()).limit(size).all()

    items = []
    for session, analysis in results:
        # Calculate duration in minutes
        duration_min = 0
        if session.end_time:
            duration_min = int((session.end_time - session.start_time).total_seconds() / 60)
            
        items.append({
            "result_id": analysis.result_id,
            "session_id": session.session_id,
            "date": session.start_time.strftime("%Y-%m-%d"),
            "start_time": session.start_time.strftime("%H:%M"),
            "duration_min": duration_min,
            "focus_score": analysis.focus_score,
            "status": session.status
        })

    # Return items array as per teammate's spec
    return jsonify({"items": items}), 200

# 1. Daily Summary API
@app.route('/api/dashboard/daily', methods=['GET'])
def get_daily_summary():
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token) # Identify the user
    
    target_date = request.args.get('date') # Expected format YYYY-MM-DD

    # Query: Sum total time and average score for today
    stats = db.session.query(
        func.sum(MetricSummary.total_time_sec).label('total_sec'),
        func.avg(AnalysisResult.focus_score).label('avg_score'),
        func.count(StudySession.session_id).label('session_count')
    ).join(AnalysisResult, StudySession.session_id == AnalysisResult.session_id)\
     .join(MetricSummary, AnalysisResult.result_id == MetricSummary.result_id)\
     .filter(StudySession.user_id == user_uuid)\
     .filter(func.date(StudySession.start_time) == target_date).first()

    return jsonify({
        "date": target_date,
        "total_study_min": int((stats.total_sec or 0) / 60),
        "avg_focus_score": round(stats.avg_score or 0, 1),
        "session_count": stats.session_count or 0
    }), 200

# 2. Weekly/Monthly Summary API
@app.route('/api/dashboard/summary', methods=['GET'])
def get_range_summary():
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token)
    
    range_type = request.args.get('range') # 'weekly' or 'monthly'

    # Calculate the time window (e.g., 7 days ago)
    from datetime import timedelta
    days_to_subtract = 7 if range_type == 'weekly' else 30
    start_date = datetime.utcnow() - timedelta(days=days_to_subtract)

    # Query real totals from your DB
    stats = db.session.query(
        func.sum(MetricSummary.total_time_sec).label('total_sec'),
        func.avg(AnalysisResult.focus_score).label('avg_score'),
        func.count(func.distinct(func.date(StudySession.start_time))).label('active_days')
    ).join(AnalysisResult, StudySession.session_id == AnalysisResult.session_id)\
     .join(MetricSummary, AnalysisResult.result_id == MetricSummary.result_id)\
     .filter(StudySession.user_id == user_uuid)\
     .filter(StudySession.start_time >= start_date).first()

    return jsonify({
        "range": range_type,
        "total_study_min": int((stats.total_sec or 0) / 60), # 실시간 계산된 분 단위
        "avg_focus_score": round(stats.avg_score or 0, 1), # 평균 집중도
        "active_days": stats.active_days or 0 # 실제 학습한 일수
    }), 200

@app.route('/api/results/<result_id>', methods=['GET', 'DELETE'])
def handle_result_detail(result_id):
    # 1. Authorization Check (공통 로직)
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized"}), 401
    
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token)

    # 2. DELETE 요청 처리
    if request.method == 'DELETE':
        # MetricSummary 먼저 삭제 (Foreign Key 제약 조건 때문)
        MetricSummary.query.filter_by(result_id=result_id).delete()
        
        analysis = AnalysisResult.query.get(result_id)
        if analysis:
            db.session.delete(analysis)
            db.session.commit()
            return jsonify({"deleted": True}), 200
        return jsonify({"message": "결과를 찾을 수 없습니다."}), 404

    # 3. GET 요청 처리 (기존 상세 조회 로직)
    result = db.session.query(AnalysisResult, MetricSummary).\
        join(MetricSummary, AnalysisResult.result_id == MetricSummary.result_id).\
        filter(AnalysisResult.result_id == result_id).first()

    if not result:
        return jsonify({"message": "결과를 찾을 수 없습니다."}), 404

    analysis, summary = result
    return jsonify({
        "summary": {
            "total_time_min": int(summary.total_time_sec / 60),
            "focus_ratio": int(summary.focus_ratio * 100),
            "focus_time_min": int(summary.focus_time_sec / 60),
            "non_focus_time_min": int(summary.non_focus_time_sec / 60)
        },
        "timeline": [{"time": "14:30", "score": 80}, {"time": "15:00", "score": 90}],
        "habit_events": [
            {"type": "posture", "count": 12, "desc": "평균보다 적음 (양호)"},
            {"type": "gaze", "count": 8, "desc": "평균 수준"}
        ],
        "created_at": analysis.created_at.strftime("%Y-%m-%d %H:%M")
    }), 200

@app.route('/api/results', methods=['GET'])
def get_all_results():
    # 1. Authorization
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1]
    user_uuid = tokens.get(token)

    # 2. Get pagination parameters from query string
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 10, type=int)

    # 3. Query with Pagination
    pagination = db.session.query(StudySession, AnalysisResult).\
        join(AnalysisResult, StudySession.session_id == AnalysisResult.session_id).\
        filter(StudySession.user_id == user_uuid).\
        order_by(StudySession.start_time.desc()).\
        paginate(page=page, per_page=size, error_out=False)

    items = []
    for session, analysis in pagination.items:
        duration_min = int((session.end_time - session.start_time).total_seconds() / 60) if session.end_time else 0
        items.append({
            "result_id": analysis.result_id,
            "date": session.start_time.strftime("%Y-%m-%d"),
            "time": session.start_time.strftime("%H:%M"),
            "duration": f"{duration_min}m",
            "score": analysis.focus_score,
            "status": session.status
        })

    # 4. Return metadata for the UI to build page numbers
    return jsonify({
        "items": items,
        "page": page,
        "size": size,
        "total": pagination.total # Total number of records in DB
    }), 200