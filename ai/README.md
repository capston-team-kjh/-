# AI quick run (Windows)

1) venv 만들고 설치
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "numpy<2" -r ai\requirements.txt

2) 실행 (config는 기본으로 ai/config/default.yaml 사용)
.\.venv\Scripts\python.exe ai\run_local.py --session-id S002 --video "C:\path\to\video.mp4" --camera-type front --mode absent --out output.json
