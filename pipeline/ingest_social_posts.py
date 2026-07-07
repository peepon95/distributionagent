"""Import founder social posts from CSV/JSONL into the research corpus.

Usage:
    python -m pipeline.ingest_social_posts path/to/posts.csv
    python -m pipeline.ingest_social_posts path/to/posts.jsonl --channel founder_posts

The importer is intentionally file-based. X, TikTok, Instagram, and Threads
usually require auth, paid APIs, or brittle browser scraping, so the reliable
workflow is: export/curate posts with a source URL, then import them here.

Required fields: platform, url, content
Optional fields: author, handle, title, published_at, metrics
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pipeline.config import RAW_DATA_DIR
from pipeline.db import existing_video_ids, upsert_episode
from pipeline.util import slugify

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"platform", "url", "content"}
DEFAULT_CHANNEL = "founder_social_posts"


def _stable_id(platform: str, url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"social_{slugify(platform)}_{digest}"


def _title(row: dict[str, str]) -> str:
    if title := row.get("title", "").strip():
        return title
    author = row.get("author", "").strip() or row.get("handle", "").strip() or "Founder"
    platform = row.get("platform", "").strip() or "social"
    content = " ".join(row.get("content", "").split())
    preview = content[:72] + ("..." if len(content) > 72 else "")
    return f"{author} on {platform}: {preview}"


def _published_at(row: dict[str, str]) -> str:
    raw = row.get("published_at", "").strip()
    if raw:
        return raw
    return datetime.now(timezone.utc).isoformat()


def row_to_episode(row: dict[str, str], channel: str) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if not row.get(field, "").strip()]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    platform = row["platform"].strip()
    url = row["url"].strip()
    content = row["content"].strip()
    author = row.get("author", "").strip()
    handle = row.get("handle", "").strip()
    metrics = row.get("metrics", "").strip()

    context = [
        f"Platform: {platform}",
        f"Author: {author}" if author else "",
        f"Handle: {handle}" if handle else "",
        f"Metrics: {metrics}" if metrics else "",
        f"Post: {content}",
    ]
    transcript_text = "\n".join(part for part in context if part)

    return {
        "video_id": _stable_id(platform, url),
        "channel": channel,
        "title": _title(row),
        "url": url,
        "published_at": _published_at(row),
        "duration": None,
        "transcript": [{"text": transcript_text, "start": 0}],
    }


def iter_rows(path: Path) -> Iterable[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="") as file:
            yield from csv.DictReader(file)
        return
    if suffix in {".jsonl", ".ndjson"}:
        with path.open() as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSONL row") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: row must be an object")
                yield {str(k): "" if v is None else str(v) for k, v in row.items()}
        return
    raise ValueError("input must be .csv, .jsonl, or .ndjson")


def episode_path(channel: str, video_id: str) -> Path:
    return RAW_DATA_DIR / channel / f"{video_id}.json"


def ingest_file(path: Path, channel: str = DEFAULT_CHANNEL, limit: int | None = None) -> None:
    in_db = existing_video_ids()
    saved = skipped = failed = 0
    for index, row in enumerate(iter_rows(path), start=1):
        if limit is not None and saved >= limit:
            break
        try:
            payload = row_to_episode(row, channel)
        except ValueError as exc:
            failed += 1
            logger.warning("Skipping row %d: %s", index, exc)
            continue

        video_id = payload["video_id"]
        output = episode_path(channel, video_id)
        if video_id in in_db or output.exists():
            skipped += 1
            continue

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        upsert_episode(payload)
        saved += 1
        logger.info("Saved %s", output.relative_to(RAW_DATA_DIR))

    logger.info("Done: %d saved, %d skipped, %d failed", saved, skipped, failed)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ingest_file(args.path, channel=args.channel, limit=args.limit)


if __name__ == "__main__":
    main()
