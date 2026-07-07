"""Enrich raw episodes with gpt-5-mini: summary, apps, founders, tactics, metrics.

Usage:
    python -m pipeline.enrich [--budget 25] [--max-episodes N] [--dry-run]

For every raw episode JSON whose `episodes.summary` is still null, calls
gpt-5-mini with pipeline/prompts/enrich_v1.txt. Transcripts longer than
WINDOW_TOKENS are enriched per ~15k-token window and merged with a final
dedupe call (prompts/enrich_merge_v1.txt). Results are stored on the episodes
row; app/founder names are upserted into `entities`.

Cost control: estimates token cost first and logs it to RUN_LOG.md. If the
estimate exceeds the budget, only the most recent 150 episodes are enriched.
A hard tracker also aborts the run if real spend crosses the budget.
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from pathlib import Path
from typing import Any

from pipeline.config import PROJECT_ROOT, RAW_DATA_DIR
from pipeline.db import get_client, upsert_episode
from pipeline.llm import (
    ENRICH_MODEL,
    BudgetExceeded,
    CostTracker,
    chat_json,
    cost_usd,
    count_tokens,
)
from pipeline.runlog import log, log_raw

logger = logging.getLogger(__name__)

PROMPT_DIR = PROJECT_ROOT / "pipeline" / "prompts"
WINDOW_TOKENS = 15_000
BUDGET_FALLBACK_EPISODES = 150
# Estimation constants: prompt template overhead and typical completion size
# (gpt-5-mini reasoning tokens bill as output, hence the generous number).
PROMPT_OVERHEAD_TOKENS = 700
OUTPUT_TOKENS_PER_CALL = 1_600


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text()


def load_raw_episodes() -> list[dict[str, Any]]:
    episodes = [
        json.loads(path.read_text()) for path in sorted(RAW_DATA_DIR.glob("*/*.json"))
    ]
    logger.info("Found %d raw episode files", len(episodes))
    return episodes


def fetch_enriched_video_ids() -> set[str]:
    """video_ids whose episodes row already has a summary."""
    client = get_client()
    if client is None:
        raise SystemExit("Supabase is not configured; enrichment needs the database")
    ids: set[str] = set()
    offset, page = 0, 1000
    while True:
        rows = (
            client.table("episodes")
            .select("video_id")
            .not_.is_("summary", "null")
            .range(offset, offset + page - 1)
            .execute()
            .data
        )
        ids.update(r["video_id"] for r in rows)
        if len(rows) < page:
            return ids
        offset += page


def transcript_text(episode: dict[str, Any]) -> str:
    return " ".join(seg["text"] for seg in episode["transcript"])


def windows_for(text: str) -> list[str]:
    """Split text into ~WINDOW_TOKENS windows on whitespace boundaries."""
    total = count_tokens(text)
    if total <= WINDOW_TOKENS:
        return [text]
    words = text.split()
    n_windows = ceil(total / WINDOW_TOKENS)
    per_window = ceil(len(words) / n_windows)
    return [
        " ".join(words[i : i + per_window]) for i in range(0, len(words), per_window)
    ]


def estimate_episode_cost(episode: dict[str, Any]) -> float:
    tokens = count_tokens(transcript_text(episode))
    n_windows = max(1, ceil(tokens / WINDOW_TOKENS))
    input_tokens = tokens + n_windows * PROMPT_OVERHEAD_TOKENS
    output_tokens = n_windows * OUTPUT_TOKENS_PER_CALL
    if n_windows > 1:  # merge call reads the partials back in
        input_tokens += n_windows * 900 + 400
        output_tokens += OUTPUT_TOKENS_PER_CALL
    return cost_usd(ENRICH_MODEL, input_tokens, output_tokens)


def enrich_episode(episode: dict[str, Any], tracker: CostTracker) -> dict[str, Any]:
    """Run windowed extraction (+ merge when multi-window) for one episode."""
    template = load_prompt("enrich_v1.txt")
    partials = [
        chat_json(
            template.format(
                title=episode["title"], channel=episode["channel"], transcript=window
            ),
            tracker=tracker,
        )
        for window in windows_for(transcript_text(episode))
    ]
    if len(partials) == 1:
        return partials[0]
    merge_template = load_prompt("enrich_merge_v1.txt")
    return chat_json(
        merge_template.format(
            title=episode["title"],
            channel=episode["channel"],
            n=len(partials),
            partials=json.dumps(partials, ensure_ascii=False),
        ),
        tracker=tracker,
    )


def store_enrichment(episode: dict[str, Any], result: dict[str, Any]) -> None:
    client = get_client()
    assert client is not None
    upsert_episode(episode)  # ensure the row exists before updating it
    client.table("episodes").update(
        {
            "summary": result.get("summary", ""),
            "apps_mentioned": result.get("apps_mentioned", []),
            "tactics": result.get("tactics", []),
            "metrics": result.get("metrics", []),
        }
    ).eq("video_id", episode["video_id"]).execute()


def upsert_entities(episode: dict[str, Any], result: dict[str, Any]) -> None:
    """Merge this episode's apps/founders/tactic-channels into `entities`.

    entities.episode_ids stores video_id strings (stable across DB rebuilds).
    """
    client = get_client()
    assert client is not None
    wanted: list[tuple[str, str]] = []
    wanted += [(a["name"], "app") for a in result.get("apps_mentioned", []) if a.get("name")]
    wanted += [(f, "founder") for f in result.get("founders", []) if f]
    wanted += [
        (t["channel"], "channel_tactic")
        for t in result.get("tactics", [])
        if t.get("channel")
    ]
    if not wanted:
        return

    names = list({name for name, _ in wanted})
    existing = {
        (row["name"].lower(), row["type"]): row
        for row in client.table("entities")
        .select("name, type, episode_ids")
        .in_("name", names)
        .execute()
        .data
    }
    rows = []
    for name, etype in dict.fromkeys(wanted):
        prior = existing.get((name.lower(), etype), {})
        episode_ids = set(prior.get("episode_ids") or [])
        episode_ids.add(episode["video_id"])
        rows.append(
            {
                "name": prior.get("name", name),
                "type": etype,
                "episode_ids": sorted(episode_ids),
            }
        )
    client.table("entities").upsert(rows, on_conflict="name,type").execute()


def run(budget_usd: float, max_episodes: int | None, dry_run: bool) -> None:
    enriched = fetch_enriched_video_ids()
    pending = [e for e in load_raw_episodes() if e["video_id"] not in enriched]
    pending.sort(key=lambda e: e.get("published_at") or "", reverse=True)
    if max_episodes is not None:
        pending = pending[:max_episodes]

    estimate = sum(estimate_episode_cost(e) for e in pending)
    log(f"Enrichment estimate: {len(pending)} episodes, ~${estimate:.2f} "
        f"(budget ${budget_usd:.2f})")
    logger.info("Estimate: %d episodes, ~$%.2f", len(pending), estimate)

    if estimate > budget_usd:
        pending = pending[:BUDGET_FALLBACK_EPISODES]
        capped = sum(estimate_episode_cost(e) for e in pending)
        log_raw(
            f"- Estimate exceeded budget: enriching only the most recent "
            f"{len(pending)} episodes (~${capped:.2f}) per standing decision."
        )
        logger.warning("Budget cap: only %d most recent episodes", len(pending))

    if dry_run:
        logger.info("Dry run; stopping before API calls")
        return

    tracker = CostTracker(budget_usd=budget_usd)
    done = failed = 0
    # LLM calls run concurrently; DB writes stay on this thread so entity
    # upserts (read-modify-write) can't race.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(enrich_episode, episode, tracker): episode
            for episode in pending
        }
        try:
            for future in as_completed(futures):
                episode = futures[future]
                try:
                    result = future.result()
                    store_enrichment(episode, result)
                    upsert_entities(episode, result)
                    done += 1
                    if done % 25 == 0 or done == len(pending):
                        logger.info(
                            "[%d/%d] enriched ($%.2f so far)",
                            done, len(pending), tracker.total_usd,
                        )
                except BudgetExceeded:
                    raise
                except Exception as exc:  # one bad episode must not kill the run
                    failed += 1
                    logger.error("Failed %s: %s", episode["video_id"], exc)
        except BudgetExceeded as exc:
            pool.shutdown(cancel_futures=True)
            log(f"Enrichment HALTED on budget: {exc}")
            logger.error("%s", exc)

    log(f"Enrichment done: {done} enriched, {failed} failed.\n"
        f"Actual spend:\n{tracker.summary()}")
    logger.info("Done: %d ok, %d failed, spend $%.2f", done, failed, tracker.total_usd)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=25.0, help="Max USD spend")
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Estimate only")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run(args.budget, args.max_episodes, args.dry_run)


if __name__ == "__main__":
    main()
