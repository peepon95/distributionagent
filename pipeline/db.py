"""Supabase client helpers for the ingestion pipeline."""

from __future__ import annotations

import logging
from functools import lru_cache

from supabase import Client, create_client

from pipeline.config import env

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> Client | None:
    """Return a Supabase client, or None if credentials are not configured."""
    url = env("SUPABASE_URL")
    key = env("SUPABASE_SERVICE_KEY")
    if not url or not key:
        logger.warning(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY not set; "
            "skipping database checks (file-based idempotency only)."
        )
        return None
    return create_client(url, key)


def upsert_episode(payload: dict[str, object]) -> None:
    """Insert/update an episodes row keyed on video_id. No-op if DB unset."""
    client = get_client()
    if client is None:
        return
    row = {
        "video_id": payload["video_id"],
        "channel": payload["channel"],
        "title": payload["title"],
        "url": payload["url"],
        "published_at": payload.get("published_at") or None,
        "duration": payload.get("duration"),
    }
    client.table("episodes").upsert(row, on_conflict="video_id").execute()


def episode_exists(video_id: str) -> bool:
    """True if an episode with this video_id is already in the database."""
    client = get_client()
    if client is None:
        return False
    result = (
        client.table("episodes")
        .select("id")
        .eq("video_id", video_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def existing_video_ids() -> set[str]:
    """All video_ids already in the episodes table (one paginated query)."""
    client = get_client()
    if client is None:
        return set()
    ids: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        result = (
            client.table("episodes")
            .select("video_id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        ids.update(row["video_id"] for row in result.data)
        if len(result.data) < page_size:
            return ids
        offset += page_size
