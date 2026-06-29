from __future__ import annotations

import os


# The user starts this worker through Codex so that every final result is held
# for visual review instead of calling a paid external vision API.
os.environ["CODEX_MANUAL_REVIEW_ENABLED"] = "true"
os.environ["OPENAI_VISION_ENABLED"] = "false"
os.environ["OPENAI_VISION_DRY_RUN"] = "true"
os.environ["OPENAI_VISION_APPLY_CORRECTION"] = "false"

from worker import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
