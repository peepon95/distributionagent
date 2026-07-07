from pipeline.ingest_social_posts import row_to_episode


def test_row_to_episode_shapes_social_post():
    episode = row_to_episode(
        {
            "platform": "x",
            "author": "Example Founder",
            "handle": "@founder",
            "url": "https://x.com/founder/status/123",
            "published_at": "2026-01-01T00:00:00Z",
            "content": "Building in public: here is the launch post.",
            "metrics": "120 likes",
        },
        "founder_social_posts",
    )

    assert episode["video_id"].startswith("social_x_")
    assert episode["channel"] == "founder_social_posts"
    assert episode["url"] == "https://x.com/founder/status/123"
    assert "Building in public" in episode["transcript"][0]["text"]
    assert "120 likes" in episode["transcript"][0]["text"]
