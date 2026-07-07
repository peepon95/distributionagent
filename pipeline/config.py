"""Shared configuration: loads .env and exposes project paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
RAW_DATA_DIR: Path = PROJECT_ROOT / "data" / "raw"

load_dotenv(PROJECT_ROOT / ".env")


def env(name: str) -> str | None:
    """Return an environment variable, treating empty strings as unset."""
    value = os.environ.get(name, "").strip()
    return value or None
