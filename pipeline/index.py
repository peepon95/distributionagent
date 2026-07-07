"""Chunk, embed, and upsert transcripts into the `chunks` table.

Usage:
    python -m pipeline.index [--limit N]

- ~800-token chunks with ~100-token overlap, each keeping the start timestamp
  of its first transcript segment.
- Episode summaries (when enrichment has run) are indexed as their own chunk
  with start_timestamp = -1 and, when the column exists, chunk_type='summary',
  so broad thematic questions can retrieve summaries.
- Embeddings: text-embedding-3-small, batches of 100.
- Every inserted chunk is also appended to a local vector cache
  (data/index/) so hybrid search can run vector similarity without the
  pgvector RPC (see pipeline/schema_v2.sql for the server-side upgrade).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from postgrest.exceptions import APIError

from pipeline.config import PROJECT_ROOT, RAW_DATA_DIR
from pipeline.db import get_client
from pipeline.enrich import load_raw_episodes
from pipeline.llm import CostTracker, count_tokens, embed_batch
from pipeline.runlog import log

logger = logging.getLogger(__name__)

INDEX_DIR = PROJECT_ROOT / "data" / "index"
CACHE_JSONL = INDEX_DIR / "cache.jsonl"
SHARD_DIR = INDEX_DIR / "shards"

CHUNK_TOKENS = 800
OVERLAP_TOKENS = 100
EMBED_BATCH_SIZE = 100
INSERT_BATCH_SIZE = 50
SUMMARY_SENTINEL = -1  # start_timestamp marking summary chunks

_has_chunk_type_column: bool | None = None


@dataclass
class Chunk:
    content: str
    start_timestamp: int
    is_summary: bool = False


def chunk_transcript(
    segments: list[dict[str, Any]],
    *,
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    """Group transcript segments into ~chunk_tokens chunks with overlap.

    Segments are never split; the overlap carries whole trailing segments
    totalling >= overlap_tokens into the next chunk, so each chunk's
    start_timestamp is a real segment start.
    """
    chunks: list[Chunk] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        chunks.append(
            Chunk(
                content=" ".join(s["text"] for s in current),
                start_timestamp=int(current[0]["start"]),
            )
        )
        # seed the next chunk with the trailing overlap
        kept: list[dict[str, Any]] = []
        kept_tokens = 0
        for seg in reversed(current):
            if kept_tokens >= overlap_tokens:
                break
            kept.insert(0, seg)
            kept_tokens += count_tokens(seg["text"])
        current = kept
        current_tokens = kept_tokens

    for seg in segments:
        seg_tokens = count_tokens(seg["text"])
        if current and current_tokens + seg_tokens > chunk_tokens:
            flush()
        current.append(seg)
        current_tokens += seg_tokens

    if current and (not chunks or current_tokens > OVERLAP_TOKENS):
        chunks.append(
            Chunk(
                content=" ".join(s["text"] for s in current),
                start_timestamp=int(current[0]["start"]),
            )
        )
    return chunks


def fetch_episode_rows() -> dict[str, dict[str, Any]]:
    """video_id -> episodes row (id, title, channel, url, summary)."""
    client = get_client()
    if client is None:
        raise SystemExit("Supabase is not configured; indexing needs the database")
    rows: dict[str, dict[str, Any]] = {}
    offset, page = 0, 1000
    while True:
        batch = (
            client.table("episodes")
            .select("id, video_id, title, channel, url, summary")
            .range(offset, offset + page - 1)
            .execute()
            .data
        )
        rows.update({r["video_id"]: r for r in batch})
        if len(batch) < page:
            return rows
        offset += page


def fetch_indexed_episode_ids() -> set[int]:
    client = get_client()
    assert client is not None
    ids: set[int] = set()
    offset, page = 0, 1000
    while True:
        batch = (
            client.table("chunks")
            .select("episode_id")
            .range(offset, offset + page - 1)
            .execute()
            .data
        )
        ids.update(r["episode_id"] for r in batch)
        if len(batch) < page:
            return ids
        offset += page


def _insert_chunk_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert chunk rows, adapting to whether chunks.chunk_type exists."""
    global _has_chunk_type_column
    client = get_client()
    assert client is not None
    if _has_chunk_type_column is False:
        for row in rows:
            row.pop("chunk_type", None)
    try:
        inserted = client.table("chunks").insert(rows).execute().data
        if _has_chunk_type_column is None and any("chunk_type" in r for r in rows):
            _has_chunk_type_column = True
        return inserted
    except APIError as exc:
        if "chunk_type" in str(exc.message):
            _has_chunk_type_column = False
            logger.info("chunks.chunk_type column absent; using start_timestamp=-1 sentinel only")
            for row in rows:
                row.pop("chunk_type", None)
            return client.table("chunks").insert(rows).execute().data
        raise


def _append_cache(entries: list[dict[str, Any]], vectors: list[list[float]]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    with CACHE_JSONL.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    shard = SHARD_DIR / f"{int(time.time() * 1000)}.npz"
    np.savez_compressed(
        shard,
        ids=np.array([e["id"] for e in entries], dtype=np.int64),
        vectors=np.array(vectors, dtype=np.float32),
    )


def index_pending(limit: int | None = None) -> None:
    episodes_by_vid = fetch_episode_rows()
    indexed = fetch_indexed_episode_ids()

    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw in load_raw_episodes():
        row = episodes_by_vid.get(raw["video_id"])
        if row is None:
            from pipeline.db import upsert_episode  # backfill: JSON exists, row doesn't

            upsert_episode(raw)
            episodes_by_vid = fetch_episode_rows()
            row = episodes_by_vid[raw["video_id"]]
        if row["id"] not in indexed:
            pending.append((raw, row))
    # Skip not-yet-enriched episodes: indexing marks an episode done, so doing
    # it before enrichment would permanently lose its summary chunk.
    unenriched = sum(1 for _, row in pending if not row.get("summary"))
    pending = [(raw, row) for raw, row in pending if row.get("summary")]
    if limit is not None:
        pending = pending[:limit]
    logger.info(
        "Indexing %d episodes (%d already indexed, %d awaiting enrichment)",
        len(pending), len(indexed), unenriched,
    )

    tracker = CostTracker()
    buffer: list[tuple[dict[str, Any], Chunk]] = []  # (episode row, chunk)
    total_chunks = 0

    def flush_buffer() -> None:
        nonlocal buffer, total_chunks
        if not buffer:
            return
        vectors = embed_batch([c.content for _, c in buffer], tracker=tracker)
        rows = [
            {
                "episode_id": row["id"],
                "content": chunk.content,
                "start_timestamp": chunk.start_timestamp,
                "embedding": vec,
                "chunk_type": "summary" if chunk.is_summary else "transcript",
            }
            for (row, chunk), vec in zip(buffer, vectors)
        ]
        inserted: list[dict[str, Any]] = []
        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            inserted.extend(_insert_chunk_rows(rows[i : i + INSERT_BATCH_SIZE]))
        _append_cache(
            [
                {
                    "id": ins["id"],
                    "video_id": row["video_id"],
                    "title": row["title"],
                    "channel": row["channel"],
                    "url": row["url"],
                    "start": chunk.start_timestamp,
                    "content": chunk.content,
                    "is_summary": chunk.is_summary,
                }
                for ins, (row, chunk) in zip(inserted, buffer)
            ],
            vectors,
        )
        total_chunks += len(buffer)
        logger.info("Indexed %d chunks so far ($%.3f embeddings)", total_chunks, tracker.total_usd)
        buffer = []

    for raw, row in pending:
        for chunk in chunk_transcript(raw["transcript"]):
            buffer.append((row, chunk))
        if row.get("summary"):
            buffer.append(
                (
                    row,
                    Chunk(
                        content=f'{row["title"]}. {row["summary"]}',
                        start_timestamp=SUMMARY_SENTINEL,
                        is_summary=True,
                    ),
                )
            )
        if len(buffer) >= EMBED_BATCH_SIZE:
            flush_buffer()
    flush_buffer()

    log(f"Indexing done: {total_chunks} chunks across {len(pending)} episodes.\n"
        f"Embedding spend:\n{tracker.summary()}")
    logger.info("Done: %d chunks, spend $%.3f", total_chunks, tracker.total_usd)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max episodes to index")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    index_pending(limit=args.limit)


if __name__ == "__main__":
    main()
