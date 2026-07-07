"""Email notifications for weekly update runs."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from pipeline.config import env
from pipeline.ingest_youtube import VideoMeta

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_TO = "eevontan95@gmail.com"


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipient: str

    @classmethod
    def from_env(cls) -> "EmailConfig | None":
        host = env("SMTP_HOST")
        user = env("SMTP_USER")
        password = env("SMTP_PASSWORD")
        if not host or not user or not password:
            return None

        port = int(env("SMTP_PORT") or "587")
        return cls(
            host=host,
            port=port,
            user=user,
            password=password,
            sender=env("EMAIL_FROM") or user,
            recipient=env("EMAIL_TO") or DEFAULT_EMAIL_TO,
        )


def build_new_videos_email(videos: list[VideoMeta]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"DistributionGPT: {len(videos)} new video(s) added"

    lines = [
        f"{len(videos)} new video(s) were added to DistributionGPT:",
        "",
    ]
    for index, video in enumerate(videos, start=1):
        lines.extend(
            [
                f"{index}. {video.title}",
                f"   Published: {video.published_at}",
                f"   URL: {video.url}",
                "",
            ]
        )

    message.set_content("\n".join(lines).rstrip() + "\n")
    return message


def send_new_videos_email(videos: list[VideoMeta]) -> bool:
    if not videos:
        logger.info("No new videos saved; skipping email notification")
        return False

    config = EmailConfig.from_env()
    if not config:
        logger.warning(
            "SMTP_HOST, SMTP_USER, and SMTP_PASSWORD are not set; "
            "skipping email notification"
        )
        return False

    message = build_new_videos_email(videos)
    message["From"] = config.sender
    message["To"] = config.recipient

    with smtplib.SMTP(config.host, config.port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(config.user, config.password)
        smtp.send_message(message)

    logger.info("Sent new-video email notification to %s", config.recipient)
    return True
