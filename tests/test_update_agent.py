"""Tests for the weekly update agent helpers."""

from __future__ import annotations

from pipeline import ingest_youtube
from pipeline.update import pending_video_ids


def test_pending_video_ids_skips_known_local_and_no_transcript(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(ingest_youtube, "RAW_DATA_DIR", tmp_path)
    channel_dir = tmp_path / "superwallhq"
    channel_dir.mkdir()
    (channel_dir / "local.json").write_text("{}")
    (channel_dir / ".no_transcript_marked").touch()

    pending = pending_video_ids(
        "superwallhq",
        ["known", "local", "marked", "fresh"],
        known={"known"},
    )

    assert pending == ["fresh"]
