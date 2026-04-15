import csv
import logging
import os
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)


def now() -> datetime:
    """
    Canonical timestamp source for diary entries.
    Returns a tz-aware local-time datetime so that serialized ISO strings keep their offset
    and later analysis can align events across entry types.
    """
    return datetime.now().astimezone()


def to_local(dt: datetime) -> datetime:
    """Normalize any datetime to tz-aware local time. Naive input is assumed to be UTC
    (PTB v21 message.date is UTC-aware, but be defensive in case that ever changes)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def append_text(timestamp: datetime, text: str) -> None:
    _write_entry(timestamp, text)


def append_audio(timestamp: datetime, transcript: str, file_path: str) -> None:
    body = f"*[Audio: {os.path.basename(file_path)}]*\n\n{transcript}"
    _write_entry(timestamp, body)


def append_mood(timestamp: datetime, level: int, label: str) -> None:
    body = f"**Mood check-in:** {label} ({level}/5)"
    _write_entry(timestamp, body)
    _append_mood_csv(timestamp, level, label)


def _write_entry(timestamp: datetime, body: str) -> None:
    os.makedirs(config.DIARY_DIR, exist_ok=True)
    date_str = timestamp.strftime("%Y-%m-%d")
    md_path = os.path.join(config.DIARY_DIR, f"{date_str}.md")
    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n---\n\n")
        f.write(f"**{timestamp.strftime('%Y-%m-%d %H:%M')}**\n\n")
        f.write(f"{body}\n")
    logger.info("Diary entry written to %s", md_path)


def _append_mood_csv(timestamp: datetime, level: int, label: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(config.MOOD_CSV)), exist_ok=True)
    file_exists = os.path.exists(config.MOOD_CSV)
    with open(config.MOOD_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "level", "label"])
        writer.writerow([timestamp.isoformat(), level, label])
