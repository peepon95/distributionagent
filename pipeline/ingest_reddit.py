"""Ingest top posts from marketing subreddits as episode-shaped JSON.

Usage:
    python -m pipeline.ingest_reddit [--limit 5]

For each subreddit, pages through the public top.json listings (all-time and
past-year) via Reddit's unauthenticated JSON endpoints, keeps substantial text
posts (selftext >= 400 chars, score >= 10), fetches up to 8 strong top-level
comments per post, and writes data/raw/reddit_{sub}/{post_id}.json in the same
shape as the YouTube episodes: the post body is the first transcript segment
and each kept comment is a "Top comment:" segment, all with start=0. Posts
that already have a JSON file or an `episodes` row are skipped, so re-runs
are idempotent.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from xml.etree import ElementTree

import requests

from pipeline.config import RAW_DATA_DIR
from pipeline.db import existing_video_ids, upsert_episode
from pipeline.util import with_retries

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "marketing",
    "appbusiness",
    "content_marketing",
    "socialmediamarketing",
    "SaaS",
    "startups",
    "SideProject",
    "Entrepreneur",
    "EntrepreneurRideAlong",
    "GrowthHacking",
]
LISTING_TIMEFRAMES = ("all", "year")
USER_AGENT = "DistributionGPT/0.1 (research corpus)"
REQUEST_DELAY_SECONDS = 2.5
RATE_LIMIT_COOLDOWN_SECONDS = 60
RATE_LIMIT_STREAK_LIMIT = 3  # consecutive 429s before abandoning the subreddit
MAX_POSTS_PER_LISTING = 200
PAGE_SIZE = 100

MIN_SELFTEXT_CHARS = 400
MIN_POST_SCORE = 10
MAX_COMMENTS = 8
MIN_COMMENT_SCORE = 5
MIN_COMMENT_CHARS = 80


class RateLimited(RuntimeError):
    """Reddit responded with HTTP 429."""


class Blocked(RuntimeError):
    """Reddit hard-refused the request (HTTP 403); retrying won't help."""


class SubredditAborted(RuntimeError):
    """Too many consecutive 429s; give up on this subreddit."""


def _fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET a Reddit JSON endpoint with retries on transient errors."""

    def call() -> Any:
        response = requests.get(
            url, params=params, timeout=30, headers={"User-Agent": USER_AGENT}
        )
        if response.status_code == 429:
            raise RateLimited(url)
        if response.status_code == 403:
            # Reddit blocks its JSON API at the CDN edge for flagged IPs;
            # this is not transient, so don't burn retries on it.
            raise Blocked(f"HTTP 403 (blocked) for {url}")
        response.raise_for_status()
        return response.json()

    return with_retries(call, retry_on=(requests.RequestException,))


def _polite_get(
    url: str,
    params: dict[str, Any],
    state: dict[str, int],
    fetcher: Callable[[str, dict[str, Any] | None], Any] | None = None,
) -> Any:
    """Rate-limited GET: pause between calls, cool down on 429, abort on a streak."""
    while True:
        try:
            result = (fetcher or _fetch_json)(url, params)
        except RateLimited:
            state["streak"] += 1
            if state["streak"] >= RATE_LIMIT_STREAK_LIMIT:
                raise SubredditAborted(url) from None
            logger.warning(
                "HTTP 429 from Reddit (%d/%d); cooling down %ds",
                state["streak"], RATE_LIMIT_STREAK_LIMIT, RATE_LIMIT_COOLDOWN_SECONDS,
            )
            time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
            continue
        state["streak"] = 0
        time.sleep(REQUEST_DELAY_SECONDS)
        return result


def keep_post(post: dict[str, Any]) -> bool:
    """True if this is a substantial text post worth learning from."""
    selftext = (post.get("selftext") or "").strip()
    return (
        bool(post.get("is_self"))
        and selftext not in ("[removed]", "[deleted]")
        and post.get("removed_by_category") is None
        and not post.get("stickied")
        and len(selftext) >= MIN_SELFTEXT_CHARS
        and int(post.get("score", 0)) >= MIN_POST_SCORE
    )


def extract_comments(payload: Any) -> list[str]:
    """Pull up to MAX_COMMENTS strong top-level comment bodies from a
    /comments/{id}.json response ([post_listing, comment_listing])."""
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    children = payload[1].get("data", {}).get("children", [])
    kept: list[str] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        body = (data.get("body") or "").strip()
        if body in ("[removed]", "[deleted]"):
            continue
        if len(body) < MIN_COMMENT_CHARS or int(data.get("score", 0)) < MIN_COMMENT_SCORE:
            continue
        kept.append(body)
        if len(kept) >= MAX_COMMENTS:
            break
    return kept


def post_to_episode(sub: str, post: dict[str, Any], comments: list[str]) -> dict[str, Any]:
    """Shape a Reddit post + comments into the episode payload used everywhere."""
    published = datetime.fromtimestamp(float(post["created_utc"]), tz=timezone.utc)
    transcript: list[dict[str, Any]] = [
        {"text": (post.get("selftext") or "").strip(), "start": 0}
    ]
    transcript.extend({"text": f"Top comment: {c}", "start": 0} for c in comments)
    return {
        "video_id": f"reddit_{post['id']}",
        "channel": f"r/{sub}",
        "title": post["title"],
        "url": f"https://www.reddit.com{post['permalink']}",
        "published_at": published.isoformat(),
        "duration": None,
        "transcript": transcript,
    }


def episode_path(sub: str, post_id: str) -> Path:
    return RAW_DATA_DIR / f"reddit_{sub}" / f"{post_id}.json"


def iter_listing_posts(sub: str, timeframe: str, state: dict[str, int]) -> Iterator[dict[str, Any]]:
    """Yield post dicts from r/{sub}/top.json?t={timeframe}, paging via `after`."""
    url = f"https://www.reddit.com/r/{sub}/top.json"
    after: str | None = None
    fetched = 0
    while fetched < MAX_POSTS_PER_LISTING:
        params: dict[str, Any] = {"t": timeframe, "limit": PAGE_SIZE}
        if after:
            params["after"] = after
        data = _polite_get(url, params, state)
        children = data.get("data", {}).get("children", [])
        if not children:
            return
        for child in children:
            yield child["data"]
        fetched += len(children)
        after = data.get("data", {}).get("after")
        if not after:
            return


def fetch_top_comments(permalink: str, state: dict[str, int]) -> list[str]:
    url = f"https://www.reddit.com{permalink.rstrip('/')}.json"
    payload = _polite_get(url, {"limit": 20, "sort": "top"}, state)
    return extract_comments(payload)


# --- RSS fallback -----------------------------------------------------------
# Reddit's edge blocks unauthenticated *.json for many ISP/CGNAT IPs but keeps
# .rss feeds open. RSS carries no scores, so quality filtering degrades to
# text length, and listings cap at ~100 posts per feed.

ATOM_NS = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_BOILERPLATE_RE = re.compile(r"submitted by\s+/u/.*$", re.S)


def _fetch_xml(url: str, params: dict[str, Any] | None = None) -> ElementTree.Element:
    """GET a Reddit .rss endpoint; same 429/403 semantics as _fetch_json."""

    def call() -> ElementTree.Element:
        response = requests.get(
            url, params=params, timeout=30, headers={"User-Agent": USER_AGENT}
        )
        if response.status_code == 429:
            raise RateLimited(url)
        if response.status_code == 403:
            raise Blocked(f"HTTP 403 (blocked) for {url}")
        response.raise_for_status()
        return ElementTree.fromstring(response.content)

    return with_retries(call, retry_on=(requests.RequestException,))


def html_fragment_to_text(fragment: str) -> str:
    """Escaped-HTML RSS content -> plain text, minus Reddit's footer boilerplate."""
    text = html.unescape(fragment)
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = _BOILERPLATE_RE.sub("", text)
    text = re.sub(r"\[link\]\s*\[comments\]\s*$", "", text.strip())
    return re.sub(r"[ \t]+", " ", text).strip()


def _rss_entries(root: ElementTree.Element) -> list[dict[str, str]]:
    entries = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        content = entry.find(f"{ATOM_NS}content")
        link = entry.find(f"{ATOM_NS}link")
        entries.append(
            {
                "id": (entry.findtext(f"{ATOM_NS}id") or "").strip(),
                "title": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                "url": link.get("href", "") if link is not None else "",
                "published": (
                    entry.findtext(f"{ATOM_NS}published")
                    or entry.findtext(f"{ATOM_NS}updated")
                    or ""
                ).strip(),
                "text": html_fragment_to_text(content.text or "")
                if content is not None and content.text
                else "",
            }
        )
    return entries


def _rss_comments(post_url: str, state: dict[str, int]) -> list[str]:
    """Top comments for a thread via its .rss feed; [] if unavailable."""
    try:
        root = _polite_get(
            f"{post_url.rstrip('/')}/.rss", {"limit": 20}, state, fetcher=_fetch_xml
        )
    except (Blocked, SubredditAborted, requests.RequestException, ElementTree.ParseError):
        return []
    kept = [
        e["text"]
        for e in _rss_entries(root)
        if e["id"].startswith("t1_") and len(e["text"]) >= MIN_COMMENT_CHARS
    ]
    return kept[:MAX_COMMENTS]


def ingest_subreddit_rss(
    sub: str, in_db: set[str], limit: int | None = None
) -> tuple[int, int, int]:
    """RSS-based ingest for one subreddit (no scores: length filter only)."""
    saved = skipped = comments_kept = 0
    seen: set[str] = set()
    state = {"streak": 0}
    try:
        for timeframe in LISTING_TIMEFRAMES:
            logger.info("r/%s: scanning top .rss (t=%s)", sub, timeframe)
            root = _polite_get(
                f"https://www.reddit.com/r/{sub}/top/.rss",
                {"t": timeframe, "limit": PAGE_SIZE},
                state,
                fetcher=_fetch_xml,
            )
            for entry in _rss_entries(root):
                post_id = entry["id"].removeprefix("t3_")
                if not post_id or post_id in seen or not entry["url"]:
                    continue
                seen.add(post_id)
                if len(entry["text"]) < MIN_SELFTEXT_CHARS:
                    continue
                if episode_path(sub, post_id).exists() or f"reddit_{post_id}" in in_db:
                    skipped += 1
                    continue
                if limit is not None and saved >= limit:
                    logger.info("r/%s: reached --limit %d", sub, limit)
                    return saved, skipped, comments_kept
                comments = _rss_comments(entry["url"], state)
                transcript = [{"text": entry["text"], "start": 0}]
                transcript.extend(
                    {"text": f"Top comment: {c}", "start": 0} for c in comments
                )
                payload = {
                    "video_id": f"reddit_{post_id}",
                    "channel": f"r/{sub}",
                    "title": entry["title"],
                    "url": entry["url"],
                    "published_at": entry["published"] or None,
                    "duration": None,
                    "transcript": transcript,
                }
                path = episode_path(sub, post_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                upsert_episode(payload)
                saved += 1
                comments_kept += len(comments)
                logger.info(
                    "Saved %s via RSS (%d comments): %s",
                    path.relative_to(RAW_DATA_DIR), len(comments), entry["title"][:70],
                )
    except SubredditAborted:
        logger.error("r/%s (rss): aborting after repeated 429s; saved work is kept", sub)
    except Blocked as exc:
        logger.error("r/%s (rss): %s — even RSS is blocked here", sub, exc)
    except (requests.RequestException, ElementTree.ParseError) as exc:
        logger.error("r/%s (rss): giving up (%s); saved work is kept", sub, exc)
    return saved, skipped, comments_kept


def ingest_subreddit(
    sub: str, in_db: set[str], limit: int | None = None
) -> tuple[int, int, int]:
    """Ingest one subreddit; returns (saved, skipped_existing, comments_kept)."""
    saved = skipped = comments_kept = 0
    seen: set[str] = set()
    state = {"streak": 0}
    try:
        for timeframe in LISTING_TIMEFRAMES:
            logger.info("r/%s: scanning top (t=%s)", sub, timeframe)
            for post in iter_listing_posts(sub, timeframe, state):
                post_id = post["id"]
                if post_id in seen:
                    continue
                seen.add(post_id)
                if not keep_post(post):
                    continue
                if episode_path(sub, post_id).exists() or f"reddit_{post_id}" in in_db:
                    skipped += 1
                    continue
                if limit is not None and saved >= limit:
                    logger.info("r/%s: reached --limit %d", sub, limit)
                    return saved, skipped, comments_kept
                comments = fetch_top_comments(post["permalink"], state)
                payload = post_to_episode(sub, post, comments)
                path = episode_path(sub, post_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                upsert_episode(payload)
                saved += 1
                comments_kept += len(comments)
                logger.info(
                    "Saved %s (%d comments): %s",
                    path.relative_to(RAW_DATA_DIR), len(comments), post["title"][:70],
                )
    except SubredditAborted:
        logger.error(
            "r/%s: aborting after %d consecutive 429s; saved work is kept",
            sub, RATE_LIMIT_STREAK_LIMIT,
        )
    except Blocked as exc:
        logger.warning("r/%s: JSON API blocked (%s); falling back to RSS", sub, exc)
        rss_saved, rss_skipped, rss_comments = ingest_subreddit_rss(sub, in_db, limit=limit)
        return saved + rss_saved, skipped + rss_skipped, comments_kept + rss_comments
    except requests.RequestException as exc:
        logger.error("r/%s: giving up after repeated failures (%s); saved work is kept", sub, exc)
    return saved, skipped, comments_kept


def ingest_all(limit: int | None = None, subs: list[str] | None = None) -> None:
    in_db = existing_video_ids()
    total_saved = total_skipped = total_comments = 0
    for sub in subs or SUBREDDITS:
        saved, skipped, comments_kept = ingest_subreddit(sub, in_db, limit=limit)
        logger.info(
            "r/%s done: %d saved, %d already ingested, %d comments kept",
            sub, saved, skipped, comments_kept,
        )
        total_saved += saved
        total_skipped += skipped
        total_comments += comments_kept
    logger.info(
        "Done: %d posts saved (%d comments), %d skipped (already ingested)",
        total_saved, total_comments, total_skipped,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max new posts per subreddit")
    parser.add_argument(
        "--subreddit", action="append", default=None,
        help="Only ingest this subreddit (repeatable); default: all four",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest_all(limit=args.limit, subs=args.subreddit)


if __name__ == "__main__":
    main()
