-- MySQL/RDS migration for AI personal feedback persistence and session duration.
-- Run this after the existing tables are present. This file alters existing tables only.

SET @schema_name = DATABASE();

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE analysis_feedback ADD COLUMN personal_feedback JSON NULL AFTER feedback_text',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'analysis_feedback'
      AND COLUMN_NAME = 'personal_feedback'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE analysis_feedback ADD COLUMN feedback_source VARCHAR(30) NULL AFTER personal_feedback',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'analysis_feedback'
      AND COLUMN_NAME = 'feedback_source'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE analysis_feedback ADD COLUMN feedback_version VARCHAR(30) NULL AFTER feedback_source',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'analysis_feedback'
      AND COLUMN_NAME = 'feedback_version'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE analysis_feedback ADD COLUMN feedback_created_at DATETIME NULL AFTER feedback_version',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'analysis_feedback'
      AND COLUMN_NAME = 'feedback_created_at'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE focus_sessions ADD COLUMN duration_sec INT NULL AFTER end_time',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'focus_sessions'
      AND COLUMN_NAME = 'duration_sec'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE analysis_feedback
SET feedback_version = COALESCE(feedback_version, 'feedback-v1')
WHERE feedback_version IS NULL;

UPDATE analysis_feedback
SET feedback_created_at = COALESCE(feedback_created_at, updated_at, CURRENT_TIMESTAMP)
WHERE feedback_created_at IS NULL;

UPDATE focus_sessions
SET duration_sec = TIMESTAMPDIFF(SECOND, start_time, end_time)
WHERE duration_sec IS NULL
  AND start_time IS NOT NULL
  AND end_time IS NOT NULL
  AND end_time >= start_time;

UPDATE focus_sessions
SET duration_sec = TIMESTAMPDIFF(SECOND, start_time, DATE_ADD(end_time, INTERVAL 1 DAY))
WHERE duration_sec IS NULL
  AND start_time IS NOT NULL
  AND end_time IS NOT NULL
  AND end_time < start_time
  AND DATE(end_time) = DATE(start_time);
