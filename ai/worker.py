from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

# 프로젝트 최상위 폴더 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# AI 실행 파일 경로
RUN_LOCAL_PATH = PROJECT_ROOT / "ai" / "run_local.py"

# 분석 결과 JSON 저장 위치
OUTPUT_JSON_PATH = PROJECT_ROOT / "output.json"

# 서버에서 받아온 영상을 임시 저장할 파일 경로
TEMP_VIDEO_PATH = PROJECT_ROOT / "temp_video.mp4"

# 백엔드 팀과 확인해서 실제 서버 주소로 변경
# 예:
# "http://127.0.0.1:8000" -> 내 컴퓨터에서 백엔드 실행할 때
# "http://서버IP:8000" -> AWS 서버 IP로 접속할 때
# "https://실제도메인" -> 도메인 연결된 경우
SERVER_BASE_URL = "실제 서버 주소"

# 백엔드 팀과 동일하게 맞춰야 하는 AI 전용 인증 키
# 백엔드에서도 같은 키를 검사하도록 설정해야 함
AI_API_KEY = "백엔드와 맞춘 AI 전용 키"


def get_next_job():
    try:
        response = requests.post(
            # 백엔드에서 만들어줘야 하는 API
            # 역할: 분석할 다음 작업 1개 내려주기
            f"{SERVER_BASE_URL}/ai/jobs/next",
            headers={"X-AI-KEY": AI_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # 백엔드 응답 형식과 맞춰야 함
        # job_id, session_id, camera_type, video_url 이 포함되어야 함
        if not data or data.get("job_id") is None:
            return None

        return data
    except Exception as e:
        print("작업 요청 실패:", e)
        return None


def download_video(video_url: str) -> Path:
    # 백엔드가 내려준 video_url로 영상 다운로드
    response = requests.get(video_url, timeout=60)
    response.raise_for_status()

    with open(TEMP_VIDEO_PATH, "wb") as f:
        f.write(response.content)

    return TEMP_VIDEO_PATH


def run_analysis(job):
    # 백엔드 응답에 video_url이 있어야 함
    video_path = download_video(job["video_url"])

    cmd = [
        sys.executable,
        str(RUN_LOCAL_PATH),
        "--video",
        str(video_path),
        "--session-id",
        job["session_id"],   # 백엔드가 내려주는 세션 ID
        "--camera-type",
        job["camera_type"],  # 백엔드가 내려주는 카메라 타입(front / overhead)
    ]

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
    )

    if result.returncode != 0:
        return {
            "job_id": job["job_id"],
            "session_id": job["session_id"],
            "status": "failed",
            "error": {
                "code": "RUN_LOCAL_ERROR",
                "message": "run_local.py 실행 실패",
            },
        }

    with open(OUTPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 백엔드가 보낸 job_id를 결과에도 같이 넣어서 다시 전송
    data["job_id"] = job["job_id"]
    return data


def send_result_to_server(result_data):
    try:
        response = requests.post(
            # 백엔드에서 만들어줘야 하는 API
            # 역할: AI 분석 결과 받아서 DB 저장
            f"{SERVER_BASE_URL}/ai/results",
            headers={"X-AI-KEY": AI_API_KEY},
            json=result_data,
            timeout=30,
        )
        response.raise_for_status()
        print("결과 전송 성공")
    except Exception as e:
        print("결과 전송 실패:", e)


def main():
    while True:
        job = get_next_job()

        if not job:
            print("가져올 작업 없음. 10초 후 다시 확인")
            time.sleep(10)
            continue

        print(f"작업 받음: job_id={job['job_id']}, session_id={job['session_id']}")
        result_data = run_analysis(job)
        send_result_to_server(result_data)

        # 다음 작업 확인 전 잠깐 대기
        time.sleep(3)


if __name__ == "__main__":
    main()