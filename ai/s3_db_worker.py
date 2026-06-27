from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_DIR = PROJECT_ROOT / "ai"
RUN_LOCAL_PATH = AI_DIR / "run_local.py"
DEFAULT_CONFIG_PATH = AI_DIR / "config" / "default.yaml"
DOWNLOAD_DIR = AI_DIR / "downloads"
OUTPUT_DIR = AI_DIR / "outputs"
DEFAULT_ANALYSIS_FEEDBACK_TABLE = "analysis_feedback"
PLACEHOLDER_VALUES = {
    "your-s3-bucket-name",
    "your-access-key-id",
    "your-secret-access-key",
    "your-rds-endpoint.amazonaws.com",
    "your-db-user",
    "your-db-password",
    "your-db-name",
}

r"""
PowerShell run example:

.\.venv\Scripts\python.exe ai\s3_db_worker.py `
  --session-id S002 `
  --camera-type front `
  --s3-key "videos/session-S002-front.mp4"

Required table SQL is documented in docs/analysis_tables.sql.
"""


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    value = value.strip()
    if value in PLACEHOLDER_VALUES:
        raise RuntimeError(f"Environment variable {name} still has a placeholder value")
    return value


def _safe_filename(value: str) -> str:
    name = Path(value).name or value
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _download_from_s3(s3_key: str, session_id: str) -> Path:
    import boto3
    from botocore.exceptions import ClientError

    bucket = _required_env("S3_BUCKET")
    region = _required_env("AWS_REGION")
    access_key = _required_env("AWS_ACCESS_KEY_ID")
    secret_key = _required_env("AWS_SECRET_ACCESS_KEY")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_session_id = _safe_filename(session_id)
    safe_object_name = _safe_filename(s3_key)
    download_path = DOWNLOAD_DIR / f"{safe_session_id}_{safe_object_name}"

    print(f"[s3] downloading s3://{bucket}/{s3_key} -> {download_path}")
    client = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    try:
        size_bytes = _get_s3_object_size(client, bucket, s3_key)
        if download_path.exists() and download_path.stat().st_size == size_bytes:
            print(f"[s3] using cached download: {download_path}")
            return download_path

        progress = _DownloadProgress(size_bytes)
        client.download_file(
            bucket,
            s3_key,
            str(download_path),
            Callback=progress,
        )
        progress.done()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            print(f"[s3] object not found: s3://{bucket}/{s3_key}")
            _print_s3_key_candidates(client, bucket, s3_key)
        elif error_code in {"403", "AccessDenied"}:
            print(f"[s3] access denied for s3://{bucket}/{s3_key}")
            print("[s3] check IAM s3:GetObject permission and bucket policy")
        raise
    print("[s3] download complete")
    return download_path


def _get_s3_object_size(client: Any, bucket: str, s3_key: str) -> int:
    response = client.head_object(Bucket=bucket, Key=s3_key)
    return int(response.get("ContentLength") or 0)


class _DownloadProgress:
    def __init__(self, total_bytes: int) -> None:
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.started_at = time.time()
        self.last_print_at = 0.0
        self.last_printed_mb = -1

        if total_bytes > 0:
            print(f"[s3] object size: {_format_bytes(total_bytes)}")

    def __call__(self, bytes_amount: int) -> None:
        self.downloaded_bytes += bytes_amount
        now = time.time()
        downloaded_mb = int(self.downloaded_bytes / (1024 * 1024))

        if now - self.last_print_at < 5 and downloaded_mb - self.last_printed_mb < 100:
            return

        self.last_print_at = now
        self.last_printed_mb = downloaded_mb
        elapsed = max(now - self.started_at, 0.001)
        speed = self.downloaded_bytes / elapsed

        if self.total_bytes > 0:
            percent = (self.downloaded_bytes / self.total_bytes) * 100
            print(
                "[s3] progress: "
                f"{_format_bytes(self.downloaded_bytes)} / "
                f"{_format_bytes(self.total_bytes)} "
                f"({percent:.1f}%, {_format_bytes(speed)}/s)"
            )
        else:
            print(
                "[s3] progress: "
                f"{_format_bytes(self.downloaded_bytes)} "
                f"({_format_bytes(speed)}/s)"
            )

    def done(self) -> None:
        if self.total_bytes > 0:
            print(
                "[s3] progress: "
                f"{_format_bytes(self.total_bytes)} / "
                f"{_format_bytes(self.total_bytes)} (100.0%)"
            )


def _format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _print_s3_key_candidates(client: Any, bucket: str, s3_key: str) -> None:
    prefix = s3_key.rsplit("/", 1)[0] + "/" if "/" in s3_key else ""
    prefixes = [prefix] if prefix else [""]
    if prefix:
        prefixes.append("")

    for candidate_prefix in prefixes:
        label = candidate_prefix or "(bucket root)"
        try:
            response = client.list_objects_v2(
                Bucket=bucket,
                Prefix=candidate_prefix,
                MaxKeys=20,
            )
        except Exception as exc:
            print(f"[s3] could not list keys under {label}: {exc}")
            continue

        contents = response.get("Contents") or []
        if not contents:
            print(f"[s3] no objects found under prefix: {label}")
            continue

        print(f"[s3] found object keys under {label}:")
        for item in contents:
            print(f"  - {item.get('Key')}")
        return


def _run_existing_analysis(
    session_id: str,
    camera_type: str,
    video_path: Path,
    output_path: Path,
    mode: str,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(RUN_LOCAL_PATH),
        "--session-id",
        session_id,
        "--video",
        str(video_path),
        "--camera-type",
        camera_type,
        "--mode",
        mode,
        "--config",
        str(DEFAULT_CONFIG_PATH),
        "--out",
        str(output_path),
    ]

    print(f"[analysis] running existing analysis: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"run_local.py failed with exit code {result.returncode}")
    print(f"[analysis] result saved: {output_path}")


def _read_result_json(output_path: Path) -> dict[str, Any]:
    with output_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _db_connection() -> Any:
    import pymysql

    return pymysql.connect(
        host=_required_env("DB_HOST"),
        port=int(_required_env("DB_PORT")),
        user=_required_env("DB_USER"),
        password=_required_env("DB_PASSWORD"),
        database=_required_env("DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _sanitize_sql_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""):
        raise RuntimeError(f"Invalid SQL identifier: {value!r}")
    return value


def _analysis_feedback_table() -> str:
    return _sanitize_sql_identifier(
        os.getenv("ANALYSIS_FEEDBACK_TABLE", DEFAULT_ANALYSIS_FEEDBACK_TABLE).strip()
        or DEFAULT_ANALYSIS_FEEDBACK_TABLE
    )


def _number_or_none(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Any:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        texts = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                texts.append(text)
        return texts

    text = _text_or_none(value)
    return [text] if text else []


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        return None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _personal_feedback_from_result(result: dict[str, Any]) -> dict[str, Any]:
    personal_feedback = result.get("personal_feedback")
    if isinstance(personal_feedback, dict):
        result.setdefault("feedback_source", "rule_based")
        result.setdefault("feedback_version", "feedback-v1")
        return personal_feedback

    try:
        if str(AI_DIR) not in sys.path:
            sys.path.insert(0, str(AI_DIR))
        from focus_ai.feedback_generator import generate_personal_feedback_payload

        feedback_payload = generate_personal_feedback_payload(result)
        personal_feedback = feedback_payload.get("personal_feedback")
        result["feedback_source"] = feedback_payload.get("feedback_source", "rule_based")
        result["feedback_version"] = feedback_payload.get("feedback_version", "feedback-v1")
    except Exception:
        personal_feedback = {}
        result.setdefault("feedback_source", "fallback")
        result.setdefault("feedback_version", "feedback-v1")

    if isinstance(personal_feedback, dict):
        result["personal_feedback"] = personal_feedback
        return personal_feedback

    return {}


def _feedback_row_from_result(session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    personal_feedback = _personal_feedback_from_result(result)
    personal_feedback_json = None
    if personal_feedback:
        personal_feedback_json = json.dumps(_json_safe(personal_feedback), ensure_ascii=False)

    time_patterns = result.get("time_patterns")
    if not isinstance(time_patterns, dict):
        time_patterns = {
            "insights": [],
        }

    feedback = result.get("feedback")
    if not isinstance(feedback, dict):
        feedback = {}

    insights = _text_list(time_patterns.get("insights"))
    lines = insights
    if not lines:
        lines = []
        for key in ("summary_text", "weak_point", "recommendation"):
            lines.extend(_text_list(feedback.get(key)))

    return {
        "session_id": session_id,
        "feedback_text": "\n".join(lines),
        "personal_feedback": personal_feedback_json,
        "feedback_source": str(result.get("feedback_source") or "rule_based"),
        "feedback_version": str(result.get("feedback_version") or "feedback-v1"),
    }


def _save_result_to_db(result: dict[str, Any]) -> None:
    session_id = str(result.get("session_id") or "").strip()
    if not session_id:
        raise RuntimeError("Result JSON does not contain session_id")

    summary = result.get("summary") or {}
    meta = result.get("meta") or {}
    timeline = result.get("timeline") or []
    events = result.get("events") or []
    feedback_table = _analysis_feedback_table()

    summary_row = {
        "session_id": session_id,
        "focus_ratio": _number_or_none(summary.get("focus_ratio")) or 0,
        "absent_count": _int_or_none(summary.get("absent_count")) or 0,
        "absent_total_sec": _number_or_none(summary.get("absent_total_sec")) or 0,
        "away_count": _int_or_none(summary.get("away_count")) or 0,
        "away_total_sec": _number_or_none(summary.get("away_total_sec")) or 0,
        "bad_posture_ratio": _number_or_none(summary.get("bad_posture_ratio")) or 0,
        "processing_time_sec": _number_or_none(meta.get("processing_time_sec")) or 0,
        "camera_type": str(meta.get("camera_type") or "merged"),
        "version": str(meta.get("version") or ""),
    }
    feedback_row = _feedback_row_from_result(session_id, result)

    print(f"[db] saving normalized analysis tables session_id={session_id}")
    conn = _db_connection()
    try:
        with conn.cursor() as cursor:
            _ensure_analysis_tables(cursor, feedback_table)
            _replace_analysis_rows(
                cursor,
                feedback_table,
                session_id,
                summary_row,
                feedback_row,
                timeline,
                events,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("[db] save complete")


def _ensure_analysis_tables(cursor: Any, feedback_table: str) -> None:
    cursor.execute(
        """
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
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_events (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL,
            event_type VARCHAR(50),
            start_sec FLOAT,
            end_sec FLOAT,
            score FLOAT,
            INDEX idx_analysis_events_session_id (session_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_timeline (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL,
            t FLOAT,
            state VARCHAR(50),
            INDEX idx_analysis_timeline_session_id (session_id)
        )
        """
    )
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {feedback_table} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL UNIQUE,
            feedback_text LONGTEXT NOT NULL,
            personal_feedback JSON NULL,
            feedback_source VARCHAR(30) NULL,
            feedback_version VARCHAR(30) NULL,
            feedback_created_at DATETIME NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_feedback_table_shape(cursor, feedback_table)


def _table_columns(cursor: Any, table_name: str) -> set[str]:
    cursor.execute(f"SHOW COLUMNS FROM {table_name}")
    return {str(row["Field"] if isinstance(row, dict) else row[0]) for row in cursor.fetchall()}


def _ensure_feedback_table_shape(cursor: Any, feedback_table: str) -> None:
    columns = _table_columns(cursor, feedback_table)
    if "feedback_text" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_text LONGTEXT NULL AFTER session_id")
        columns.add("feedback_text")

    if "personal_feedback" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN personal_feedback JSON NULL AFTER feedback_text")
        columns.add("personal_feedback")

    if "feedback_source" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_source VARCHAR(30) NULL AFTER personal_feedback")
        columns.add("feedback_source")

    if "feedback_version" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_version VARCHAR(30) NULL AFTER feedback_source")
        columns.add("feedback_version")

    if "feedback_created_at" not in columns:
        cursor.execute(f"ALTER TABLE {feedback_table} ADD COLUMN feedback_created_at DATETIME NULL AFTER feedback_version")
        columns.add("feedback_created_at")

    for legacy_text_column in ("insights_json", "summary_text", "weak_point", "recommendation"):
        if legacy_text_column in columns:
            cursor.execute(
                f"""
                UPDATE {feedback_table}
                SET feedback_text = COALESCE(NULLIF(feedback_text, ''), {legacy_text_column}, '')
                WHERE feedback_text IS NULL OR feedback_text = ''
                """
            )

    cursor.execute(f"UPDATE {feedback_table} SET feedback_text = '' WHERE feedback_text IS NULL")
    cursor.execute(f"ALTER TABLE {feedback_table} MODIFY feedback_text LONGTEXT NOT NULL")


def _replace_analysis_rows(
    cursor: Any,
    feedback_table: str,
    session_id: str,
    summary_row: dict[str, Any],
    feedback_row: dict[str, Any],
    timeline: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    cursor.execute("DELETE FROM analysis_timeline WHERE session_id = %s", (session_id,))
    cursor.execute("DELETE FROM analysis_events WHERE session_id = %s", (session_id,))

    cursor.execute(
        """
        INSERT INTO analysis_summary (
            session_id,
            focus_ratio,
            absent_count,
            absent_total_sec,
            away_count,
            away_total_sec,
            bad_posture_ratio,
            processing_time_sec,
            camera_type,
            version
        ) VALUES (
            %(session_id)s,
            %(focus_ratio)s,
            %(absent_count)s,
            %(absent_total_sec)s,
            %(away_count)s,
            %(away_total_sec)s,
            %(bad_posture_ratio)s,
            %(processing_time_sec)s,
            %(camera_type)s,
            %(version)s
        )
        ON DUPLICATE KEY UPDATE
            focus_ratio = VALUES(focus_ratio),
            absent_count = VALUES(absent_count),
            absent_total_sec = VALUES(absent_total_sec),
            away_count = VALUES(away_count),
            away_total_sec = VALUES(away_total_sec),
            bad_posture_ratio = VALUES(bad_posture_ratio),
            processing_time_sec = VALUES(processing_time_sec),
            camera_type = VALUES(camera_type),
            version = VALUES(version),
            analyzed_at = CURRENT_TIMESTAMP
        """,
        summary_row,
    )

    cursor.execute(
        f"""
        INSERT INTO {feedback_table} (
            session_id,
            feedback_text,
            personal_feedback,
            feedback_source,
            feedback_version,
            feedback_created_at
        ) VALUES (
            %(session_id)s,
            %(feedback_text)s,
            %(personal_feedback)s,
            %(feedback_source)s,
            %(feedback_version)s,
            CURRENT_TIMESTAMP
        )
        ON DUPLICATE KEY UPDATE
            feedback_text = VALUES(feedback_text),
            personal_feedback = VALUES(personal_feedback),
            feedback_source = VALUES(feedback_source),
            feedback_version = VALUES(feedback_version),
            feedback_created_at = VALUES(feedback_created_at),
            updated_at = CURRENT_TIMESTAMP
        """,
        feedback_row,
    )

    timeline_values = []
    for row in timeline:
        t = _number_or_none(row.get("t")) or 0
        for state in _timeline_states(row):
            timeline_values.append((session_id, t, state))

    if timeline_values:
        cursor.executemany(
            """
            INSERT INTO analysis_timeline (session_id, t, state)
            VALUES (%s, %s, %s)
            """,
            timeline_values,
        )

    event_values = [
        (
            session_id,
            str(row.get("event_type") or row.get("type") or "unknown"),
            _number_or_none(row.get("start_sec")) or 0,
            _number_or_none(row.get("end_sec")) or 0,
            _number_or_none(row.get("score")) or 0,
        )
        for row in events
    ]

    if event_values:
        cursor.executemany(
            """
            INSERT INTO analysis_events (
                session_id, event_type, start_sec, end_sec, score
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            event_values,
        )


def _timeline_states(row: dict[str, Any]) -> list[str]:
    states = row.get("states")
    if isinstance(states, list):
        clean_states = [str(state) for state in states if state]
        if clean_states:
            return clean_states

    state = row.get("state")
    if state:
        return [str(state)]

    flags = row.get("flags") or {}
    active_flags = [str(name) for name, enabled in flags.items() if enabled]
    return active_flags or ["unknown"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a video from S3, run the existing AI analysis, and save JSON to MySQL."
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--camera-type", choices=["front", "overhead"], required=True)
    parser.add_argument("--s3-key", required=True)
    parser.add_argument("--mode", choices=["dummy", "absent"], default="absent")
    args = parser.parse_args()

    try:
        _load_env()
        print(f"[worker] start session_id={args.session_id}, camera_type={args.camera_type}")
        video_path = _download_from_s3(args.s3_key, args.session_id)
        output_path = OUTPUT_DIR / f"{_safe_filename(args.session_id)}_{args.camera_type}.json"
        _run_existing_analysis(
            session_id=args.session_id,
            camera_type=args.camera_type,
            video_path=video_path,
            output_path=output_path,
            mode=args.mode,
        )
        result = _read_result_json(output_path)
        _save_result_to_db(result)
        print("[worker] success")
        return 0
    except KeyboardInterrupt:
        print("[worker] interrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[worker] failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
