import os
from datetime import datetime, time
from pathlib import Path

from dotenv import load_dotenv

# Anchor .env to the diary_bot/ directory so the script works regardless of CWD
_DOTENV_PATH = Path(__file__).parent / ".env"
load_dotenv(_DOTENV_PATH)

# Telegram
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ALLOWED_USER_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()
]
DIARY_CHAT_ID: int = int(os.getenv("DIARY_CHAT_ID", "0"))

# Storage paths
AUDIO_DIR: str = os.getenv("AUDIO_DIR", "storage/audio")
ARCHIVE_DIR: str = os.getenv("ARCHIVE_DIR", "storage/archive")
DIARY_DIR: str = os.getenv("DIARY_DIR", "storage/diary")
MOOD_CSV: str = os.getenv("MOOD_CSV", "storage/mood.csv")  # legacy single-scale mood log (unused by new flow)
MOOD_ENTRIES_CSV: str = os.getenv("MOOD_ENTRIES_CSV", "storage/mood_entries.csv")
SLEEP_CSV: str = os.getenv("SLEEP_CSV", "storage/sleep.csv")

# Transcription
TRANSCRIPTION_SERVICE: str = os.getenv("TRANSCRIPTION_SERVICE", "whisper_local")
WHISPER_MODEL_PATH: str = os.getenv("WHISPER_MODEL_PATH", "")
# On Windows this will typically be "whisper.exe"; on macOS/Linux, "whisper" or an absolute path.
WHISPER_EXE: str = os.getenv("WHISPER_EXE", "whisper")
WHISPER_LANG: str = os.getenv("WHISPER_LANG", "ru")
# Max seconds for a single whisper run. Empty / 0 = no limit (recommended on CPU).
_whisper_timeout_raw = os.getenv("WHISPER_TIMEOUT", "").strip()
WHISPER_TIMEOUT: int | None = int(_whisper_timeout_raw) if _whisper_timeout_raw and int(_whisper_timeout_raw) > 0 else None

# Voice Activity Detection (Silero VAD via whisper.cpp).
# Skips silent regions before transcription — big speedup on diary recordings with long pauses.
WHISPER_VAD: bool = os.getenv("WHISPER_VAD", "").strip().lower() in {"1", "true", "yes", "on"}
WHISPER_VAD_MODEL: str = os.getenv("WHISPER_VAD_MODEL", "")
# Optional VAD tunables — leave empty to use whisper.cpp defaults.
WHISPER_VAD_THRESHOLD: str = os.getenv("WHISPER_VAD_THRESHOLD", "").strip()
WHISPER_VAD_MIN_SILENCE_MS: str = os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "").strip()
WHISPER_VAD_SPEECH_PAD_MS: str = os.getenv("WHISPER_VAD_SPEECH_PAD_MS", "").strip()

# Path to the ffmpeg executable. Leave as "ffmpeg" to rely on PATH.
FFMPEG_EXE: str = os.getenv("FFMPEG_EXE", "ffmpeg")

# Mood check schedule — comma-separated HH:MM values (24h).
# These are BASE times; actual pings fire at a random offset within ±PING_WINDOW_MINUTES.
_mood_times_raw: str = os.getenv("MOOD_PING_TIMES", os.getenv("MOOD_CHECK_TIMES", "09:00,15:00,21:00"))
_LOCAL_TZ = datetime.now().astimezone().tzinfo


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m), tzinfo=_LOCAL_TZ)


MOOD_CHECK_TIMES: list[time] = [
    _parse_time(t.strip()) for t in _mood_times_raw.split(",") if t.strip()
]

# Daily sleep-quality question — fixed time (not randomized: it's an anchor for the morning).
SLEEP_QUESTION_TIME: time = _parse_time(os.getenv("SLEEP_QUESTION_TIME", "09:00").strip())

# Randomization window around each base mood time (± minutes).
PING_WINDOW_MINUTES: int = int(os.getenv("PING_WINDOW_MINUTES", "90"))

# Pings become unanswerable after this many minutes; late taps are rejected.
RESPONSE_TIMEOUT_MINUTES: int = int(os.getenv("RESPONSE_TIMEOUT_MINUTES", "120"))

# Minimum enforced gap when randomizing adjacent pings (re-rolled until satisfied).
MIN_GAP_BETWEEN_PINGS_MINUTES: int = int(os.getenv("MIN_GAP_BETWEEN_PINGS_MINUTES", "120"))
