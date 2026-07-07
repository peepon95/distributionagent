"""Append timestamped entries to RUN_LOG.md so long runs are auditable."""

from __future__ import annotations

from datetime import datetime

from pipeline.config import PROJECT_ROOT

RUN_LOG = PROJECT_ROOT / "RUN_LOG.md"


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M")
    with RUN_LOG.open("a") as f:
        f.write(f"\n## {stamp} — {message}\n")


def log_raw(text: str) -> None:
    with RUN_LOG.open("a") as f:
        f.write(text + "\n")
