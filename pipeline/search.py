"""Hybrid retrieval: vector similarity + Postgres full-text, merged with RRF.

Usage:
    python -m pipeline.search "tiktok growth tactics" [--k 10] [--channel X]
        [--app "Cal AI"] [--summaries-only] [--json]

Vector leg: local embedding cache written by pipeline/index.py (data/index/),
falling back to the `match_chunks` RPC if the cache is missing and the RPC
exists (see pipeline/schema_v2.sql). Keyword leg: Postgres full-text search on
chunks.tsv via PostgREST. Legs are merged with reciprocal rank fusion —
app/product names embed poorly, so the keyword leg is never skipped.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
from functools import lru_cache
from typing import Any

import numpy as np

from pipeline.db import get_client
from pipeline.index import CACHE_JSONL, SHARD_DIR, SUMMARY_SENTINEL
from pipeline.llm import embed_batch

logger = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES_PER_LEG = 40


@lru_cache(maxsize=1)
def _load_cache() -> tuple[dict[int, dict[str, Any]], np.ndarray, np.ndarray] | None:
    """Return (meta by chunk id, ids array, L2-normalized vector matrix)."""
    if not CACHE_JSONL.exists():
        return None
    meta: dict[int, dict[str, Any]] = {}
    with CACHE_JSONL.open() as f:
        for line in f:
            entry = json.loads(line)
            meta[entry["id"]] = entry
    ids_list: list[np.ndarray] = []
    vecs_list: list[np.ndarray] = []
    for shard in sorted(SHARD_DIR.glob("*.npz")):
        data = np.load(shard)
        ids_list.append(data["ids"])
        vecs_list.append(data["vectors"])
    if not ids_list:
        return None
    ids = np.concatenate(ids_list)
    vectors = np.concatenate(vecs_list).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
    return meta, ids, vectors


def _chunk_result(meta: dict[str, Any]) -> dict[str, Any]:
    start = int(meta["start"])
    is_summary = meta.get("is_summary", False) or start == SUMMARY_SENTINEL
    return {
        "chunk_id": meta["id"],
        "content": meta["content"],
        "start_timestamp": max(start, 0),
        "is_summary": is_summary,
        "video_id": meta["video_id"],
        "title": meta["title"],
        "channel": meta["channel"],
        "url": meta["url"],
        "timestamp_url": f'{meta["url"]}&t={max(start, 0)}s'
        if "youtube.com" in meta["url"]
        else meta["url"],
    }


def _allowed_video_ids(filters: dict[str, str] | None) -> set[str] | None:
    """Resolve filters to a set of video_ids, or None for no filtering."""
    if not filters:
        return None
    allowed: set[str] | None = None
    if channel := filters.get("channel"):
        cache = _load_cache()
        if cache:
            ids = {
                m["video_id"]
                for m in cache[0].values()
                if channel.lower() in m["channel"].lower()
            }
            allowed = ids
    if app := filters.get("app"):
        episodes = find_episodes_about(app)
        app_ids = {e["video_id"] for e in episodes}
        allowed = app_ids if allowed is None else allowed & app_ids
    return allowed


def _vector_leg(
    query: str, allowed: set[str] | None, summaries_only: bool, k: int
) -> list[dict[str, Any]]:
    cache = _load_cache()
    if cache is None:
        return _vector_leg_rpc(query, k)
    meta, ids, vectors = cache
    query_vec = np.array(embed_batch([query])[0], dtype=np.float32)
    query_vec /= np.linalg.norm(query_vec) + 1e-9
    scores = vectors @ query_vec
    results = []
    for idx in np.argsort(-scores):
        entry = meta.get(int(ids[idx]))
        if entry is None:
            continue
        result = _chunk_result(entry)
        if summaries_only and not result["is_summary"]:
            continue
        if allowed is not None and result["video_id"] not in allowed:
            continue
        results.append(result)
        if len(results) >= k:
            break
    return results


def _vector_leg_rpc(query: str, k: int) -> list[dict[str, Any]]:
    """Server-side pgvector search; requires schema_v2.sql to have been run."""
    client = get_client()
    if client is None:
        return []
    try:
        rows = client.rpc(
            "match_chunks",
            {"query_embedding": embed_batch([query])[0], "match_count": k},
        ).execute().data
    except Exception as exc:
        logger.warning("No local cache and match_chunks RPC unavailable: %s", exc)
        return []
    return [
        _chunk_result(
            {
                "id": r["id"],
                "content": r["content"],
                "start": r["start_timestamp"],
                "video_id": r["video_id"],
                "title": r["title"],
                "channel": r["channel"],
                "url": r["url"],
            }
        )
        for r in rows
    ]


def _fts_leg(
    query: str, allowed: set[str] | None, summaries_only: bool, k: int
) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    rows = (
        client.table("chunks")
        .select("id, content, start_timestamp, episodes!inner(video_id, title, channel, url)")
        .filter("tsv", "wfts(english)", query)  # websearch_to_tsquery
        .limit(CANDIDATES_PER_LEG)
        .execute()
        .data
    )
    results = []
    for row in rows:
        episode = row["episodes"]
        result = _chunk_result(
            {
                "id": row["id"],
                "content": row["content"],
                "start": row["start_timestamp"],
                "video_id": episode["video_id"],
                "title": episode["title"],
                "channel": episode["channel"],
                "url": episode["url"],
            }
        )
        if summaries_only and not result["is_summary"]:
            continue
        if allowed is not None and result["video_id"] not in allowed:
            continue
        results.append(result)
        if len(results) >= k:
            break
    return results


def hybrid_search(
    query: str,
    filters: dict[str, str] | None = None,
    k: int = 10,
    *,
    summaries_only: bool = False,
) -> list[dict[str, Any]]:
    """Vector + full-text retrieval merged with reciprocal rank fusion."""
    allowed = _allowed_video_ids(filters)
    legs = [
        _vector_leg(query, allowed, summaries_only, CANDIDATES_PER_LEG),
        _fts_leg(query, allowed, summaries_only, CANDIDATES_PER_LEG),
    ]
    scores: dict[int, float] = {}
    by_id: dict[int, dict[str, Any]] = {}
    for leg in legs:
        for rank, result in enumerate(leg):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id.setdefault(cid, result)
    ranked = sorted(scores, key=lambda cid: -scores[cid])[:k]
    return [{**by_id[cid], "score": round(scores[cid], 5)} for cid in ranked]


def find_episodes_about(app_name: str) -> list[dict[str, Any]]:
    """Episodes mentioning an app: exact match first, then fuzzy via entities."""
    client = get_client()
    if client is None:
        return []
    entities = (
        client.table("entities").select("name, episode_ids").eq("type", "app").execute().data
    )
    by_name = {e["name"].lower(): e for e in entities}
    match = by_name.get(app_name.lower())
    if match is None:
        close = difflib.get_close_matches(
            app_name.lower(), list(by_name), n=1, cutoff=0.75
        )
        match = by_name[close[0]] if close else None
    if match is None:
        return []
    video_ids = match["episode_ids"] or []
    if not video_ids:
        return []
    return (
        client.table("episodes")
        .select("video_id, title, channel, url, published_at, summary")
        .in_("video_id", video_ids)
        .execute()
        .data
    )


def multi_search(queries: list[str], k: int = 10) -> list[dict[str, Any]]:
    """Run several queries (e.g. one per competitor app) and RRF-merge them."""
    scores: dict[int, float] = {}
    by_id: dict[int, dict[str, Any]] = {}
    for query in queries:
        for rank, result in enumerate(hybrid_search(query, k=k)):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id.setdefault(cid, result)
    ranked = sorted(scores, key=lambda cid: -scores[cid])[:k]
    return [{**by_id[cid], "score": round(scores[cid], 5)} for cid in ranked]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--app", default=None)
    parser.add_argument("--summaries-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output (for the web app)")
    parser.add_argument(
        "--extra-queries-json",
        default=None,
        help='JSON array of additional queries to RRF-merge (e.g. per competitor)',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    if args.extra_queries_json:
        queries = [args.query] + json.loads(args.extra_queries_json)
        results = multi_search(queries, k=args.k)
    else:
        filters = {}
        if args.channel:
            filters["channel"] = args.channel
        if args.app:
            filters["app"] = args.app
        results = hybrid_search(
            args.query, filters or None, k=args.k, summaries_only=args.summaries_only
        )
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
        return
    for r in results:
        mm, ss = divmod(r["start_timestamp"], 60)
        print(f'{r["score"]:.4f}  [{r["title"]} — {r["channel"]} @ {mm}:{ss:02d}]')
        print(f'        {r["timestamp_url"]}')
        print(f'        {r["content"][:160]}…\n')


if __name__ == "__main__":
    main()
