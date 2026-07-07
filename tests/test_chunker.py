"""Tests for the transcript chunker and enrichment windowing."""

from __future__ import annotations

from pipeline.enrich import windows_for
from pipeline.index import chunk_transcript
from pipeline.llm import count_tokens


def make_segments(n: int, words_per_seg: int = 40) -> list[dict]:
    return [
        {"text": " ".join(f"word{i}x{j}" for j in range(words_per_seg)), "start": i * 10.0}
        for i in range(n)
    ]


def test_short_transcript_is_one_chunk() -> None:
    segments = make_segments(3)
    chunks = chunk_transcript(segments)
    assert len(chunks) == 1
    assert chunks[0].start_timestamp == 0
    assert "word2x39" in chunks[0].content


def test_chunks_respect_token_budget_and_overlap() -> None:
    segments = make_segments(60)  # ~40 tokens+ per segment -> several chunks
    chunks = chunk_transcript(segments, chunk_tokens=800, overlap_tokens=100)
    assert len(chunks) > 1
    for chunk in chunks:
        # never wildly over budget (one segment of slack is allowed)
        assert count_tokens(chunk.content) < 1000
    # consecutive chunks share overlap: chunk N+1 starts before chunk N ends
    for a, b in zip(chunks, chunks[1:]):
        assert b.content.split()[0] in a.content


def test_chunk_start_timestamps_are_real_segment_starts() -> None:
    segments = make_segments(60)
    starts = {int(s["start"]) for s in segments}
    for chunk in chunk_transcript(segments):
        assert chunk.start_timestamp in starts


def test_windows_for_short_text() -> None:
    assert windows_for("hello world") == ["hello world"]


def test_windows_for_long_text_splits_evenly() -> None:
    text = " ".join(f"tok{i}" for i in range(40_000))  # >> 15k tokens
    windows = windows_for(text)
    assert len(windows) >= 2
    assert " ".join(windows) == text  # nothing lost
    sizes = [count_tokens(w) for w in windows]
    assert max(sizes) <= 16_000
