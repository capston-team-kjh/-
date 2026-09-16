from __future__ import annotations

import os
import threading


# The user starts this worker through Codex so that every final result is held
# for visual review instead of calling a paid external vision API.
os.environ["CODEX_MANUAL_REVIEW_ENABLED"] = "true"
os.environ["OPENAI_VISION_ENABLED"] = "false"
os.environ["OPENAI_VISION_DRY_RUN"] = "true"
os.environ["OPENAI_VISION_APPLY_CORRECTION"] = "false"

import worker  # noqa: E402
from codex_sdk_review import run_review_worker  # noqa: E402


def main() -> int:
    # Load the same project environment before the SDK thread starts. The SQS
    # analysis loop and the review loop continue to use the existing worker and
    # RDS contracts.
    worker._load_env()
    stop_event = threading.Event()
    reviewer = threading.Thread(
        target=run_review_worker,
        args=(stop_event,),
        name="codex-sdk-frame-review",
        daemon=True,
    )
    reviewer.start()
    try:
        return worker.main()
    finally:
        stop_event.set()
        reviewer.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
