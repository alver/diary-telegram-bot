import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)

_TIMESTAMP_RE = re.compile(r"^(\d{8}_\d{6})")
_PENDING_SUFFIX = ".pending"


def _ensure_dirs() -> None:
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    os.makedirs(config.ARCHIVE_DIR, exist_ok=True)


def audio_save_path(timestamp_str: str, file_id: str, extension: str) -> str:
    """Build a deterministic file path for a downloaded audio file."""
    _ensure_dirs()
    ext = extension if extension.startswith(".") else f".{extension}"
    return os.path.join(config.AUDIO_DIR, f"{timestamp_str}_{file_id}{ext}")


def archive_mp3_path(timestamp_str: str) -> str:
    """Path of the archived 32 kbps mp3 for a given timestamp prefix."""
    _ensure_dirs()
    return os.path.join(config.ARCHIVE_DIR, f"{timestamp_str}.mp3")


def cleanup_processed(audio_path: str) -> None:
    """Remove the downloaded original, the 16k-mono WAV, and the pending marker.
    The archive mp3 stays — it's the long-term artifact referenced from the diary."""
    wav_path = os.path.splitext(audio_path)[0] + "_16k_mono.wav"
    for p in (audio_path, wav_path):
        if os.path.exists(p):
            try:
                os.unlink(p)
            except OSError:
                logger.warning("Could not remove %s", p, exc_info=True)
    clear_pending(audio_path)


def convert_to_wav_16k_mono(input_path: str) -> Optional[str]:
    """
    Convert any audio file to 16kHz mono WAV.
    Also saves a 32 kbps MP3 copy to the archive directory.
    Returns the path to the WAV file, or None on failure.
    """
    _ensure_dirs()
    input_path = os.path.abspath(input_path)
    base = os.path.splitext(os.path.basename(input_path))[0]

    match = _TIMESTAMP_RE.match(base)
    archive_base = match.group(1) if match else base

    wav_path = os.path.splitext(input_path)[0] + "_16k_mono.wav"
    mp3_path = os.path.join(config.ARCHIVE_DIR, f"{archive_base}.mp3")

    try:
        _run_ffmpeg(
            [
                config.FFMPEG_EXE, "-y", "-i", input_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                wav_path,
            ],
            description="WAV conversion",
        )
    except RuntimeError as e:
        logger.error("Audio conversion failed: %s", e)
        return None

    try:
        _run_ffmpeg(
            [
                config.FFMPEG_EXE, "-y", "-i", input_path,
                "-vn", "-acodec", "libmp3lame", "-b:a", "32k", "-ar", "16000", "-ac", "1",
                mp3_path,
            ],
            description="MP3 archive",
        )
    except RuntimeError as e:
        logger.warning("Archive MP3 creation failed (non-fatal): %s", e)

    return wav_path


def _run_ffmpeg(cmd: list[str], description: str) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{description}: {result.stderr.strip()}")


# ==========================
# Pending-file tracking
# ==========================
# A ".pending" sibling marker is created right after download and removed only
# after the diary entry is written. On startup, any surviving marker signals
# that transcription was interrupted and should be retried.

def mark_pending(audio_path: str) -> None:
    with open(audio_path + _PENDING_SUFFIX, "w", encoding="utf-8") as f:
        f.write("")


def clear_pending(audio_path: str) -> None:
    marker = audio_path + _PENDING_SUFFIX
    if os.path.exists(marker):
        os.unlink(marker)


def list_pending() -> list[str]:
    """Return absolute paths of audio files that have a pending marker."""
    if not os.path.isdir(config.AUDIO_DIR):
        return []
    pending = []
    for name in os.listdir(config.AUDIO_DIR):
        if name.endswith(_PENDING_SUFFIX):
            audio_name = name[: -len(_PENDING_SUFFIX)]
            audio_path = os.path.join(config.AUDIO_DIR, audio_name)
            if os.path.exists(audio_path):
                pending.append(os.path.abspath(audio_path))
    return pending


def timestamp_from_filename(filename: str) -> Optional[datetime]:
    """Parse the YYYYMMDD_HHMMSS prefix out of a saved audio filename (returns tz-aware local)."""
    match = _TIMESTAMP_RE.match(os.path.basename(filename))
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        return naive.astimezone()  # astimezone() on naive assumes local time
    except ValueError:
        return None
