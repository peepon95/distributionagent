"""Tests for Reddit post filtering, comment extraction, and episode shaping."""

from __future__ import annotations

from typing import Any

from pipeline.ingest_reddit import extract_comments, keep_post, post_to_episode

GOOD_POST: dict[str, Any] = {
    "id": "abc123",
    "title": "How I grew my app to 10k downloads with zero ad spend",
    "permalink": "/r/marketing/comments/abc123/how_i_grew_my_app/",
    "created_utc": 1717200000,
    "score": 250,
    "is_self": True,
    "stickied": False,
    "removed_by_category": None,
    "selftext": "x" * 450,
}


def _post(**overrides: Any) -> dict[str, Any]:
    return {**GOOD_POST, **overrides}


def test_keep_post_accepts_substantial_text_post() -> None:
    assert keep_post(GOOD_POST)


def test_keep_post_rejects_short_low_score_or_link_posts() -> None:
    assert not keep_post(_post(selftext="too short"))
    assert not keep_post(_post(score=9))
    assert not keep_post(_post(is_self=False, selftext=""))


def test_keep_post_rejects_stickied_removed_deleted() -> None:
    assert not keep_post(_post(stickied=True))
    assert not keep_post(_post(selftext="[removed]"))
    assert not keep_post(_post(selftext="[deleted]"))
    assert not keep_post(_post(removed_by_category="moderator"))


def _comment_child(body: str, score: int, kind: str = "t1") -> dict[str, Any]:
    return {"kind": kind, "data": {"body": body, "score": score}}


def test_extract_comments_filters_and_caps() -> None:
    long_body = "This tactic worked for us: " + "y" * 80
    payload = [
        {"data": {"children": []}},  # post listing (ignored)
        {
            "data": {
                "children": [
                    _comment_child(long_body, score=50),
                    _comment_child("short", score=99),  # too short
                    _comment_child(long_body, score=4),  # score too low
                    _comment_child("[removed]" + " " * 100, score=80),
                    _comment_child(long_body, score=10, kind="more"),  # not a comment
                ]
                + [_comment_child(f"{long_body} #{i}", score=20) for i in range(10)]
            }
        },
    ]
    comments = extract_comments(payload)
    assert len(comments) == 8  # capped at MAX_COMMENTS
    assert comments[0] == long_body


def test_extract_comments_handles_malformed_payload() -> None:
    assert extract_comments({"error": 404}) == []
    assert extract_comments([]) == []


def test_post_to_episode_shape() -> None:
    comments = ["Great advice, we did the same with TikTok ads and saw 3x installs."]
    episode = post_to_episode("marketing", GOOD_POST, comments)
    assert episode["video_id"] == "reddit_abc123"
    assert episode["channel"] == "r/marketing"
    assert episode["title"] == GOOD_POST["title"]
    assert episode["url"] == "https://www.reddit.com/r/marketing/comments/abc123/how_i_grew_my_app/"
    assert episode["published_at"] == "2024-06-01T00:00:00+00:00"
    assert episode["duration"] is None
    assert episode["transcript"][0] == {"text": "x" * 450, "start": 0}
    assert episode["transcript"][1] == {
        "text": f"Top comment: {comments[0]}",
        "start": 0,
    }
    assert len(episode["transcript"]) == 2
