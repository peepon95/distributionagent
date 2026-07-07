"""Tests for weekly email notifications."""

from __future__ import annotations

from pipeline.emailer import build_new_videos_email
from pipeline.ingest_youtube import VideoMeta


def test_build_new_videos_email_lists_titles_dates_and_urls() -> None:
    message = build_new_videos_email(
        [
            VideoMeta(
                video_id="abc123def45",
                title="A Fresh Superwall Video",
                published_at="2026-07-06T10:00:00Z",
                duration=123,
            )
        ]
    )

    body = message.get_content()

    assert message["Subject"] == "DistributionGPT: 1 new video(s) added"
    assert "A Fresh Superwall Video" in body
    assert "2026-07-06T10:00:00Z" in body
    assert "https://www.youtube.com/watch?v=abc123def45" in body
