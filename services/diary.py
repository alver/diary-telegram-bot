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


# ---------------- 2-D mood (pleasantness + energy) ----------------

MOOD_ENTRY_FIELDS = [
    "entry_id",
    "timestamp",
    "pleasantness",
    "energy",
    "status",
]


def append_mood_entry(
    entry_id: str,
    timestamp: datetime,
    pleasantness: int | None,
    energy: int | None,
    status: str,
) -> None:
    """Write a 2-D mood entry to the mood_entries CSV. Also writes a human-readable
    line to the daily markdown when the entry is complete or partial."""
    _append_csv(
        config.MOOD_CSV,
        MOOD_ENTRY_FIELDS,
        {
            "entry_id": entry_id,
            "timestamp": timestamp.isoformat(),
            "pleasantness": pleasantness if pleasantness is not None else "",
            "energy": energy if energy is not None else "",
            "status": status,
        },
    )
    if status == "missed":
        return
    v = pleasantness if pleasantness is not None else "—"
    a = energy if energy is not None else "—"
    _write_entry(timestamp, f"**Mood check-in:** pleasantness {v}/5, energy {a}/5 ({status})")


# ---------------- Sleep quality (PSQI component 1) ----------------

SLEEP_ENTRY_FIELDS = [
    "entry_id",
    "prompt_sent_at",
    "responded_at",
    "night_of",
    "sleep_quality",
    "status",
]


def append_sleep_entry(
    entry_id: str,
    prompt_sent_at: datetime,
    responded_at: datetime | None,
    night_of,  # datetime.date
    sleep_quality: int | None,
    status: str,
) -> None:
    _append_csv(
        config.SLEEP_CSV,
        SLEEP_ENTRY_FIELDS,
        {
            "entry_id": entry_id,
            "prompt_sent_at": prompt_sent_at.isoformat(),
            "responded_at": responded_at.isoformat() if responded_at else "",
            "night_of": night_of.isoformat(),
            "sleep_quality": sleep_quality if sleep_quality is not None else "",
            "status": status,
        },
    )
    if status == "missed" or sleep_quality is None:
        return
    ts = responded_at or prompt_sent_at
    _write_entry(ts, f"**Sleep:** night of {night_of.isoformat()} — quality {sleep_quality}/4")


def _append_csv(path: str, fieldnames: list[str], row: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def _write_entry(timestamp: datetime, body: str) -> None:
    os.makedirs(config.DIARY_DIR, exist_ok=True)
    date_str = timestamp.strftime("%Y-%m-%d")
    md_path = os.path.join(config.DIARY_DIR, f"{date_str}.md")
    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n---\n\n")
        f.write(f"**{timestamp.strftime('%Y-%m-%d %H:%M')}**\n\n")
        f.write(f"{body}\n")
    logger.info("Diary entry written to %s", md_path)
