"""Ingest all videos of a YouTube channel as transcript JSON files.

Usage:
    python -m pipeline.ingest_youtube @starterstory [--limit 3]

For each video in the channel's uploads playlist, fetches the transcript
(with timestamps) and writes data/raw/{channel}/{video_id}.json. Videos that
already have a JSON file or an `episodes` row are skipped, so re-runs are
idempotent. Videos without transcripts are logged and skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    RequestBlocked,
    YouTubeTranscriptApi,
)

from pipeline.config import RAW_DATA_DIR
from pipeline.config import env
from pipeline.db import existing_video_ids, upsert_episode
from pipeline.util import iso8601_duration_to_seconds, slugify, with_retries

logger = logging.getLogger(__name__)

import os

API_BASE = "https://www.googleapis.com/youtube/v3"
# Polite pause between transcript fetches; raise via env when YouTube is testy.
TRANSCRIPT_DELAY_SECONDS = float(os.environ.get("YT_TRANSCRIPT_DELAY", "1.5"))
BLOCK_COOLDOWN_SECONDS = 900  # one long cooldown when YouTube IP-blocks us
BLOCK_STREAK_LIMIT = 3  # consecutive blocked fetches before cooling down


class TransientlyBlocked(RuntimeError):
    """YouTube is rate-limiting/IP-blocking transcript fetches right now."""


@dataclass(frozen=True)
class VideoMeta:
    video_id: str
    title: str
    published_at: str
    duration: int  # seconds

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _api_get(api_key: str, resource: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET a YouTube Data API v3 resource with retries on transient errors."""

    def call() -> dict[str, Any]:
        response = requests.get(
            f"{API_BASE}/{resource}",
            params={**params, "key": api_key},
            timeout=30,
        )
        if response.status_code in (500, 502, 503, 504, 429):
            response.raise_for_status()
        if not response.ok:
            # 4xx other than 429: not transient, fail with the API's message.
            raise SystemExit(
                f"YouTube API error {response.status_code} on /{resource}: "
                f"{response.text[:500]}"
            )
        return response.json()

    return with_retries(call, retry_on=(requests.RequestException,))


def extract_handle(channel: str) -> str:
    """Normalize '@handle', a handle, or a channel URL to '@handle' / 'UC…' id."""
    channel = channel.strip().rstrip("/")
    match = re.search(r"youtube\.com/(?:channel/)?(@?[\w.\-]+)$", channel)
    if match:
        channel = match.group(1)
    if channel.startswith("UC"):
        return channel
    return channel if channel.startswith("@") else f"@{channel}"


def resolve_channel(api_key: str, channel: str) -> tuple[str, str]:
    """Resolve a handle or channel URL to (uploads_playlist_id, channel_slug)."""
    handle = extract_handle(channel)
    params = {"part": "contentDetails,snippet"}
    if handle.startswith("UC"):
        params["id"] = handle
    else:
        params["forHandle"] = handle
    data = _api_get(api_key, "channels", params)
    items = data.get("items") or []
    if not items:
        raise SystemExit(f"Channel not found: {channel!r}")
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    slug = slugify(
        items[0]["snippet"].get("customUrl", "").lstrip("@")
        or items[0]["snippet"]["title"]
    )
    return uploads, slug


def iter_upload_video_ids(api_key: str, playlist_id: str) -> Iterator[str]:
    """Yield every video id in the uploads playlist, newest first."""
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        data = _api_get(api_key, "playlistItems", params)
        for item in data.get("items", []):
            yield item["contentDetails"]["videoId"]
        page_token = data.get("nextPageToken")
        if not page_token:
            return


def fetch_video_meta(api_key: str, video_ids: list[str]) -> list[VideoMeta]:
    """Fetch title/publish date/duration for up to 50 video ids per call."""
    metas: list[VideoMeta] = []
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        data = _api_get(
            api_key,
            "videos",
            {"part": "snippet,contentDetails", "id": ",".join(batch)},
        )
        for item in data.get("items", []):
            metas.append(
                VideoMeta(
                    video_id=item["id"],
                    title=item["snippet"]["title"],
                    published_at=item["snippet"]["publishedAt"],
                    duration=iso8601_duration_to_seconds(
                        item["contentDetails"]["duration"]
                    ),
                )
            )
    return metas


def parse_transcript(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize raw transcript segments to [{text, start}].

    Collapses whitespace, drops empty and sound-effect-only segments
    (e.g. '[Music]'), and rounds start times to 1 decimal place.
    """
    parsed: list[dict[str, Any]] = []
    for segment in raw_segments:
        text = re.sub(r"\s+", " ", segment.get("text", "")).strip()
        if not text or re.fullmatch(r"(\[[^\]]*\]\s*)+", text):
            continue
        parsed.append({"text": text, "start": round(float(segment["start"]), 1)})
    return parsed


def fetch_transcript(video_id: str) -> list[dict[str, Any]] | None:
    """Fetch and parse a transcript; None if the video has no transcript.

    Raises TransientlyBlocked when YouTube is rate-limiting us, so callers can
    cool down instead of misclassifying pending videos as transcript-less.
    """
    api = YouTubeTranscriptApi()
    try:
        fetched = with_retries(
            lambda: api.fetch(video_id, languages=["en", "en-US", "en-GB"]),
            retry_on=(requests.RequestException,),
        )
    except (IpBlocked, RequestBlocked) as exc:
        raise TransientlyBlocked(video_id) from exc
    except CouldNotRetrieveTranscript as exc:
        logger.info("No transcript for %s (%s); skipping", video_id, type(exc).__name__)
        return None
    return parse_transcript(fetched.to_raw_data())


def episode_path(channel_slug: str, video_id: str) -> Path:
    return RAW_DATA_DIR / channel_slug / f"{video_id}.json"


def no_transcript_marker(channel_slug: str, video_id: str) -> Path:
    """Marker file so genuinely transcript-less videos aren't refetched forever."""
    return RAW_DATA_DIR / channel_slug / f".no_transcript_{video_id}"


def save_episode(channel_slug: str, meta: VideoMeta, transcript: list[dict[str, Any]]) -> Path:
    path = episode_path(channel_slug, meta.video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_id": meta.video_id,
        "channel": channel_slug,
        "title": meta.title,
        "url": meta.url,
        "published_at": meta.published_at,
        "duration": meta.duration,
        "transcript": transcript,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    upsert_episode(payload)
    return path


def ingest_channel(api_key: str, channel: str, limit: int | None = None) -> None:
    playlist_id, channel_slug = resolve_channel(api_key, channel)
    logger.info("Channel %s -> uploads playlist %s", channel_slug, playlist_id)

    video_ids = list(iter_upload_video_ids(api_key, playlist_id))
    logger.info("Found %d videos", len(video_ids))

    in_db = existing_video_ids()
    pending = [
        vid
        for vid in video_ids
        if vid not in in_db
        and not episode_path(channel_slug, vid).exists()
        and not no_transcript_marker(channel_slug, vid).exists()
    ]
    skipped = len(video_ids) - len(pending)
    if limit is not None:
        pending = pending[:limit]
    logger.info("Ingesting %d videos (%d already ingested)", len(pending), skipped)

    metas = fetch_video_meta(api_key, pending)
    # Longest videos first: YouTube rate-limits transcript fetches to ~20-30
    # per IP, so spend each window on full interviews before Shorts.
    if os.environ.get("YT_PRIORITIZE_LONG", "1") != "0":
        metas.sort(key=lambda m: m.duration, reverse=True)

    saved = no_transcript = blocked = 0
    block_streak = 0
    cooled_down = False
    for meta in metas:
        try:
            transcript = fetch_transcript(meta.video_id)
        except TransientlyBlocked:
            blocked += 1
            block_streak += 1
            if block_streak >= BLOCK_STREAK_LIMIT:
                if cooled_down:
                    logger.error(
                        "Still IP-blocked after cooldown; aborting run. "
                        "Blocked videos stay pending — re-run later to resume."
                    )
                    break
                logger.warning(
                    "YouTube is IP-blocking transcript fetches; cooling down %ds",
                    BLOCK_COOLDOWN_SECONDS,
                )
                time.sleep(BLOCK_COOLDOWN_SECONDS)
                cooled_down = True
                block_streak = 0
            continue
        block_streak = 0
        time.sleep(TRANSCRIPT_DELAY_SECONDS)
        if not transcript:
            no_transcript += 1
            marker = no_transcript_marker(channel_slug, meta.video_id)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            continue
        path = save_episode(channel_slug, meta, transcript)
        saved += 1
        logger.info("Saved %s (%d segments)", path.relative_to(RAW_DATA_DIR.parent.parent), len(transcript))

    logger.info(
        "Done: %d saved, %d without transcript, %d blocked (pending retry), "
        "%d skipped (already ingested)",
        saved, no_transcript, blocked, skipped,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", help="Channel handle (@starterstory) or URL")
    parser.add_argument("--limit", type=int, default=None, help="Max new videos to ingest")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    api_key = env("YOUTUBE_API_KEY")
    if not api_key:
        sys.exit("YOUTUBE_API_KEY is not set (add it to .env; see .env.example)")

    ingest_channel(api_key, args.channel, limit=args.limit)


if __name__ == "__main__":
    main()
