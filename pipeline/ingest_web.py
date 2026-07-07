"""Ingest article pages from socialgrowthengineers.com as episode-shaped JSON.

Usage:
    python -m pipeline.ingest_web [--limit 5]

Discovers page URLs (sitemap.xml first, falling back to crawling same-domain
links from the homepage), extracts clean article text with trafilatura, and
writes data/raw/social_growth_engineers/{slug}.json in the same shape as the
YouTube episodes: the article body becomes a single transcript segment with
start=0. Re-runs skip pages whose JSON file already exists.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
import trafilatura

from pipeline.config import RAW_DATA_DIR
from pipeline.db import upsert_episode
from pipeline.util import slugify, with_retries

logger = logging.getLogger(__name__)

SITE_URL = "https://www.socialgrowthengineers.com/"
CHANNEL_SLUG = "social_growth_engineers"
FETCH_DELAY_SECONDS = 0.8
MIN_ARTICLE_CHARS = 300  # below this, treat the page as navigation/boilerplate
NON_ARTICLE_SLUGS = {"home", "join", "about", "apps", "resources", "reports"}

_HREF = re.compile(r'href="([^"#?]+)"')


def _fetch(url: str) -> requests.Response:
    def call() -> requests.Response:
        response = requests.get(url, timeout=30, headers={"User-Agent": "DistributionGPT/0.1"})
        response.raise_for_status()
        return response

    return with_retries(call, retry_on=(requests.RequestException,))


def _same_site(url: str) -> bool:
    return urlparse(url).netloc.replace("www.", "") == urlparse(SITE_URL).netloc.replace("www.", "")


_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _sitemap_page_urls(sitemap_url: str, depth: int = 0) -> list[str]:
    """Collect page URLs from a sitemap, recursing into sitemap indexes."""
    root = ElementTree.fromstring(_fetch(sitemap_url).content)
    locs = [el.text.strip() for el in root.iter(f"{_SITEMAP_NS}loc") if el.text]
    if root.tag == f"{_SITEMAP_NS}sitemapindex" and depth < 2:
        urls: list[str] = []
        for child in locs:
            urls.extend(_sitemap_page_urls(child, depth + 1))
        return urls
    return [u for u in locs if not u.endswith(".xml")]


def discover_urls() -> list[str]:
    """Return candidate page URLs: sitemap.xml if present, else homepage links."""
    try:
        urls = _sitemap_page_urls(urljoin(SITE_URL, "/sitemap.xml"))
        if urls:
            logger.info("Found %d page URLs via sitemap.xml", len(urls))
            return urls
    except (requests.RequestException, ElementTree.ParseError):
        logger.info("No usable sitemap.xml; falling back to homepage links")

    html = _fetch(SITE_URL).text
    urls = {SITE_URL}
    for href in _HREF.findall(html):
        absolute = urljoin(SITE_URL, href)
        if _same_site(absolute) and not absolute.endswith((".png", ".jpg", ".css", ".js", ".svg")):
            urls.add(absolute.rstrip("/") + "/")
    logger.info("Found %d same-site URLs on homepage", len(urls))
    return sorted(urls)


def url_slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return slugify(path) if path else "home"


def article_path(url: str) -> Path:
    return RAW_DATA_DIR / CHANNEL_SLUG / f"{url_slug(url)}.json"


def extract_article(url: str, html: str) -> dict[str, object] | None:
    """Extract clean article text; None if the page isn't article-like."""
    text = trafilatura.extract(html, url=url, include_comments=False)
    if not text or len(text) < MIN_ARTICLE_CHARS:
        return None
    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = (metadata.title if metadata else None) or url_slug(url)
    published = metadata.date if metadata else None
    return {
        "video_id": f"web_{url_slug(url)}",
        "channel": CHANNEL_SLUG,
        "title": title,
        "url": url,
        "published_at": published,
        "duration": None,
        "transcript": [{"text": text.strip(), "start": 0}],
    }


def ingest_site(limit: int | None = None) -> None:
    urls = [
        u
        for u in discover_urls()
        if url_slug(u) not in NON_ARTICLE_SLUGS and not article_path(u).exists()
    ]
    if limit is not None:
        urls = urls[:limit]

    saved = skipped = 0
    for url in urls:
        try:
            html = _fetch(url).text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            continue
        time.sleep(FETCH_DELAY_SECONDS)

        payload = extract_article(url, html)
        if payload is None:
            skipped += 1
            logger.info("Not article-like, skipping: %s", url)
            continue

        path = article_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        upsert_episode(payload)
        saved += 1
        logger.info("Saved %s", path.name)

    logger.info("Done: %d articles saved, %d non-article pages skipped", saved, skipped)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max new pages to ingest")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest_site(limit=args.limit)


if __name__ == "__main__":
    main()
