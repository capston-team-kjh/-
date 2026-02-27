from flask import Flask, request, jsonify
# backend/app.py
from flask import Flask
from models import db, User # Import from your new file
import bcrypt

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:1234@localhost/focus_db'

# Connect the db object to your specific app
db.init_app(app)

with app.app_context():
    db.create_all() # This creates the tables based on models.py

tokens = {
    "demo-token": "b3e2a1..." # Maps token to the User UUID in MySQL
}

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    # 1. Look up the user by email in MySQL
    user = User.query.filter_by(email=email).first()

    # 2. Verify existence and check the hashed password
    if user and bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        # For your graduation demo, we'll return a simple success response
        # In a real app, 'access_token' would be a generated JWT
        generated_token = "demo-token" 
        tokens[generated_token] = user.user_id # Map it in memory

        return jsonify({
            "access_token": generated_token, 
            "user": {
                "user_id": user.user_id, # This is the UUID
                "email": user.email
            }
        }), 200

    # 3. Fail if user doesn't exist or password is wrong
    return jsonify({"error": "이메일 또는 비밀번호가 올바르지 않습니다."}), 401

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    # 1. Check if email is already taken (UK constraint)
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "이미 등록된 이메일입니다."}), 400

    # 2. Hash the password for security
    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    # 3. Create user (user_id UUID is auto-generated in models.py)
    new_user = User(
        email=email,
        password_hash=hashed_pw.decode('utf-8')
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "user_id": new_user.user_id,
        "email": new_user.email,
        "message": "User created successfully"
    }), 201

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    # In a full production system, you would 'blacklist' the token here.
    # For your graduation demo, returning a success is sufficient.
    return jsonify({"result": "ok"}), 200

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