"""OpenAI helpers: chat-as-JSON, embeddings, token counting, cost tracking."""

from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from typing import Any

import tiktoken
from openai import OpenAI

from pipeline.config import env
from pipeline.util import with_retries

logger = logging.getLogger(__name__)

ENRICH_MODEL = "gpt-5-mini"
CHAT_MODEL = "gpt-4o"
EMBED_MODEL = "text-embedding-3-small"

# USD per 1M tokens (input, output). Update if OpenAI reprices.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    api_key = env("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set (add it to .env)")
    return OpenAI(api_key=api_key)


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def encode(text: str) -> list[int]:
    return _encoding().encode(text)


def decode(tokens: list[int]) -> str:
    return _encoding().decode(tokens)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICES[model]
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


class CostTracker:
    """Accumulates real API usage and enforces a hard budget."""

    def __init__(self, budget_usd: float | None = None) -> None:
        self.budget_usd = budget_usd
        self.input_tokens: dict[str, int] = {}
        self.output_tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.input_tokens[model] = self.input_tokens.get(model, 0) + input_tokens
            self.output_tokens[model] = self.output_tokens.get(model, 0) + output_tokens
        if self.budget_usd is not None and self.total_usd > self.budget_usd:
            raise BudgetExceeded(
                f"Spend ${self.total_usd:.2f} exceeded budget ${self.budget_usd:.2f}"
            )

    @property
    def total_usd(self) -> float:
        return sum(
            cost_usd(m, self.input_tokens.get(m, 0), self.output_tokens.get(m, 0))
            for m in set(self.input_tokens) | set(self.output_tokens)
        )

    def summary(self) -> str:
        lines = [
            f"  {m}: {self.input_tokens.get(m, 0):,} in / "
            f"{self.output_tokens.get(m, 0):,} out = "
            f"${cost_usd(m, self.input_tokens.get(m, 0), self.output_tokens.get(m, 0)):.2f}"
            for m in sorted(set(self.input_tokens) | set(self.output_tokens))
        ]
        return "\n".join(lines + [f"  TOTAL: ${self.total_usd:.2f}"])


class BudgetExceeded(RuntimeError):
    pass


def chat_json(
    prompt: str,
    *,
    model: str = ENRICH_MODEL,
    tracker: CostTracker | None = None,
) -> dict[str, Any]:
    """One-shot chat call that must return a JSON object; retries once on bad JSON."""

    def call() -> dict[str, Any]:
        response = get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
        if tracker and response.usage:
            tracker.add(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
        return json.loads(response.choices[0].message.content or "{}")

    return with_retries(call, attempts=3, base_delay=2.0)


def embed_batch(
    texts: list[str], *, tracker: CostTracker | None = None
) -> list[list[float]]:
    """Embed up to ~100 texts with text-embedding-3-small."""

    def call() -> list[list[float]]:
        response = get_client().embeddings.create(model=EMBED_MODEL, input=texts)
        if tracker and response.usage:
            tracker.add(EMBED_MODEL, response.usage.prompt_tokens, 0)
        return [item.embedding for item in response.data]

    return with_retries(call, attempts=3, base_delay=2.0)
