"""Tests for the transcript parser and small helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.ingest_youtube import extract_handle, parse_transcript
from pipeline.util import iso8601_duration_to_seconds, slugify

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_raw.json"


@pytest.fixture()
def raw_segments() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_parse_transcript_keeps_real_segments(raw_segments: list[dict]) -> None:
    parsed = parse_transcript(raw_segments)
    assert [s["text"] for s in parsed] == [
        "welcome back to the show",
        "today we're talking about paywalls",
        "Superwall grew to $1M ARR",
        "by focusing on TikTok creators",
    ]


def test_parse_transcript_normalizes_whitespace(raw_segments: list[dict]) -> None:
    parsed = parse_transcript(raw_segments)
    assert parsed[1]["text"] == "today we're talking about paywalls"


def test_parse_transcript_drops_sound_effects_and_empties(raw_segments: list[dict]) -> None:
    parsed = parse_transcript(raw_segments)
    texts = {s["text"] for s in parsed}
    assert "[Music]" not in texts
    assert "" not in texts
    assert len(parsed) == 4


def test_parse_transcript_preserves_and_rounds_starts(raw_segments: list[dict]) -> None:
    parsed = parse_transcript(raw_segments)
    assert [s["start"] for s in parsed] == [0.0, 2.5, 8.3, 12.7]


def test_parse_transcript_empty_input() -> None:
    assert parse_transcript([]) == []


def test_extract_handle_variants() -> None:
    assert extract_handle("@starterstory") == "@starterstory"
    assert extract_handle("starterstory") == "@starterstory"
    assert extract_handle("https://www.youtube.com/@SuperwallHQ") == "@SuperwallHQ"
    assert extract_handle("https://www.youtube.com/@SuperwallHQ/") == "@SuperwallHQ"
    assert (
        extract_handle("https://www.youtube.com/channel/UCabc123")
        == "UCabc123"
    )


def test_iso8601_duration_to_seconds() -> None:
    assert iso8601_duration_to_seconds("PT2M30S") == 150
    assert iso8601_duration_to_seconds("PT1H2M3S") == 3723
    assert iso8601_duration_to_seconds("PT45S") == 45
    assert iso8601_duration_to_seconds("P1DT1S") == 86401
    with pytest.raises(ValueError):
        iso8601_duration_to_seconds("garbage")


def test_slugify() -> None:
    assert slugify("Starter Story") == "starter_story"
    assert slugify("blog/how-we-grew") == "blog_how_we_grew"
