"""Weekly update agent: find new/missing videos, then ingest -> enrich -> index.

Usage:
    python -m pipeline.update [--budget 25] [--skip-web]
    python -m pipeline.update --rss-only

By default, scans each channel's full uploads playlist so missed older videos
are retried as well as fresh uploads. Use --rss-only for a quick latest-video
check via YouTube RSS (limited to the newest feed items).

Also re-crawls the article site (idempotent; only new pages are fetched).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from dataclasses import dataclass

import requests

from pipeline.config import env
from pipeline.db import existing_video_ids
from pipeline.emailer import send_new_videos_email
from pipeline.ingest_youtube import (
    BLOCK_COOLDOWN_SECONDS,
    BLOCK_STREAK_LIMIT,
    TRANSCRIPT_DELAY_SECONDS,
    TransientlyBlocked,
    episode_path,
    fetch_transcript,
    fetch_video_meta,
    iter_upload_video_ids,
    no_transcript_marker,
    resolve_channel,
    save_episode,
    VideoMeta,
)
from pipeline.ingest_web import ingest_site
from pipeline.runlog import log
from pipeline.util import with_retries

logger = logging.getLogger(__name__)

CHANNELS = ["@SuperwallHQ", "@starterstory"]
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


@dataclass(frozen=True)
class ChannelUpdateResult:
    channel: str
    scanned: int
    pending: int
    saved: int
    no_transcript: int
    blocked: int
    saved_videos: list[VideoMeta]


def rss_video_ids(channel_id: str) -> list[str]:
    """Latest ~15 video ids from the channel's RSS feed (no API quota)."""
    response = with_retries(
        lambda: requests.get(RSS_URL.format(channel_id=channel_id), timeout=30),
        retry_on=(requests.RequestException,),
    )
    response.raise_for_status()
    return re.findall(r"<yt:videoId>([\w-]{11})</yt:videoId>", response.text)


def candidate_video_ids(
    api_key: str, playlist_id: str, channel_id: str, rss_only: bool
) -> list[str]:
    if rss_only:
        return rss_video_ids(channel_id)
    return list(iter_upload_video_ids(api_key, playlist_id))


def pending_video_ids(
    channel_slug: str, video_ids: list[str], known: set[str]
) -> list[str]:
    return [
        vid
        for vid in video_ids
        if vid not in known
        and not episode_path(channel_slug, vid).exists()
        and not no_transcript_marker(channel_slug, vid).exists()
    ]


def update_channel(
    api_key: str,
    handle: str,
    known: set[str],
    *,
    rss_only: bool = False,
    limit: int | None = None,
) -> ChannelUpdateResult:
    playlist_id, channel_slug = resolve_channel(api_key, handle)
    channel_id = "UC" + playlist_id[2:]  # uploads playlist is UU + channel suffix
    video_ids = candidate_video_ids(api_key, playlist_id, channel_id, rss_only)
    pending = pending_video_ids(channel_slug, video_ids, known)
    if limit is not None:
        pending = pending[:limit]

    mode = "RSS" if rss_only else "full uploads scan"
    logger.info(
        "%s: %d scanned via %s, %d pending",
        channel_slug,
        len(video_ids),
        mode,
        len(pending),
    )

    metas = fetch_video_meta(api_key, pending)
    if os.environ.get("YT_PRIORITIZE_LONG", "1") != "0":
        metas.sort(key=lambda m: m.duration, reverse=True)

    saved = no_transcript = blocked = 0
    saved_videos: list[VideoMeta] = []
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
                        "Still IP-blocked after cooldown; aborting channel update. "
                        "Blocked videos stay pending for the next weekly run."
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
        if transcript:
            save_episode(channel_slug, meta, transcript)
            known.add(meta.video_id)
            saved_videos.append(meta)
            saved += 1
            logger.info("Saved video: %s (%s)", meta.title, meta.url)
        else:
            no_transcript += 1
            marker = no_transcript_marker(channel_slug, meta.video_id)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()

    logger.info(
        "%s done: %d saved, %d without transcript, %d blocked",
        channel_slug,
        saved,
        no_transcript,
        blocked,
    )
    return ChannelUpdateResult(
        channel=channel_slug,
        scanned=len(video_ids),
        pending=len(pending),
        saved=saved,
        no_transcript=no_transcript,
        blocked=blocked,
        saved_videos=saved_videos,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=25.0)
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument(
        "--rss-only",
        action="store_true",
        help="Only check the latest RSS feed items instead of full uploads scans",
    )
    parser.add_argument(
        "--channel",
        action="append",
        dest="channels",
        help="Channel handle/URL to update. Repeat to override defaults.",
    )
    parser.add_argument(
        "--limit-per-channel",
        type=int,
        default=None,
        help="Maximum pending videos to ingest per channel in this run",
    )
    parser.add_argument(
        "--include-reddit",
        action="store_true",
        help="Also ingest founder/marketing subreddit posts before enrichment",
    )
    parser.add_argument(
        "--reddit-limit",
        type=int,
        default=None,
        help="Maximum new Reddit posts per subreddit when --include-reddit is set",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    api_key = env("YOUTUBE_API_KEY")
    if not api_key:
        raise SystemExit("YOUTUBE_API_KEY is not set")

    known = existing_video_ids()
    channels = args.channels or CHANNELS
    results = [
        update_channel(
            api_key,
            handle,
            known,
            rss_only=args.rss_only,
            limit=args.limit_per_channel,
        )
        for handle in channels
    ]
    new_total = sum(result.saved for result in results)
    blocked_total = sum(result.blocked for result in results)
    if not args.skip_web:
        ingest_site()
    if args.include_reddit:
        from pipeline.ingest_reddit import ingest_all as ingest_reddit_all

        ingest_reddit_all(limit=args.reddit_limit)

    mode = "RSS" if args.rss_only else "full uploads scan"
    log(
        f"Update: {new_total} videos ingested via {mode}; "
        f"{blocked_total} blocked/pending; running enrich + index"
    )

    from pipeline.enrich import run as enrich_run
    from pipeline.index import index_pending

    enrich_run(budget_usd=args.budget, max_episodes=None, dry_run=False)
    index_pending()

    saved_videos = [video for result in results for video in result.saved_videos]
    send_new_videos_email(saved_videos)


if __name__ == "__main__":
    main()
