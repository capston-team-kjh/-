CREATE TABLE IF NOT EXISTS analysis_summary (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    focus_ratio FLOAT,
    absent_count INT,
    absent_total_sec FLOAT,
    away_count INT,
    away_total_sec FLOAT,
    bad_posture_ratio FLOAT,
    processing_time_sec FLOAT,
    camera_type VARCHAR(50),
    version VARCHAR(50),
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(50),
    start_sec FLOAT,
    end_sec FLOAT,
    score FLOAT,
    INDEX idx_analysis_events_session_id (session_id)
);

CREATE TABLE IF NOT EXISTS analysis_timeline (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    t FLOAT,
    state VARCHAR(50),
    INDEX idx_analysis_timeline_session_id (session_id)
);

CREATE TABLE IF NOT EXISTS analysis_feedback (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    feedback_text LONGTEXT NOT NULL,
    personal_feedback JSON NULL,
    feedback_source VARCHAR(30) NULL,
    feedback_version VARCHAR(30) NULL,
    feedback_created_at DATETIME NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
