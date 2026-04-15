# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
python bot.py
```

Requires a `.env` file (see `.env.example`). Minimum vars: `BOT_TOKEN`, `ALLOWED_USER_IDS`, `DIARY_CHAT_ID`, `WHISPER_MODEL_PATH`, `WHISPER_EXE`. Optional: `FFMPEG_EXE`, `WHISPER_LANG`, `WHISPER_TIMEOUT`, `WHISPER_VAD`, `WHISPER_VAD_MODEL`, `MOOD_CHECK_TIMES`.

Dependencies: `python-telegram-bot[job-queue]`, `python-dotenv`. External binaries: `ffmpeg` and a whisper.cpp CLI build (e.g. `whisper.exe`). The legacy Pyrogram-based single-file pipeline lives under `old/` and is no longer maintained.

## Architecture

Event-driven Telegram bot built on `python-telegram-bot` v21, long-polling. Entry point `bot.py` wires handlers and a scheduled `JobQueue`.

### Packages
- `bot.py` — app bootstrap, handler registration, startup recovery, mood scheduler.
- `config.py` — all settings loaded from `.env`.
- `handlers/messages.py` — text / voice / audio message handling.
- `handlers/mood.py` — inline mood keyboard + callback handler.
- `services/audio.py` — ffmpeg WAV/MP3 conversion, pending-file tracking, archive path helpers.
- `services/diary.py` — append to daily `YYYY-MM-DD.md` files and `mood.csv`.
- `services/transcription/` — pluggable transcription backends behind `TranscriptionService` ABC. `get_transcription_service()` in `__init__.py` is the factory.
- `services/transcription/worker.py` — `TranscriptionWorker` owns a single-worker thread pool so CPU-heavy ffmpeg+whisper jobs serialize.

### Audio pipeline (success path)
1. Incoming voice/audio → downloaded to `storage/audio/{timestamp}_{file_id}.{ext}`.
2. `mark_pending()` creates a `.pending` sibling marker.
3. `TranscriptionWorker.transcribe_file()` runs ffmpeg → 16 kHz mono WAV + 32 kbps archive MP3 in `storage/archive/{timestamp}.mp3`, then invokes whisper.cpp on the WAV.
4. Diary entry appended referencing the **archive MP3 filename** (not the original download).
5. `cleanup_processed()` removes original download, WAV, and pending marker. Archive MP3 is kept.
6. Chat cleanup: user's original message, progress reply, and transcript reply are deleted after `CONFIRM_TTL` (3s) so chat history stays at zero.

### Audio pipeline (failure path)
- Transcription error: original download and pending marker are **retained** on disk. User's voice message + progress note are deleted; only the error reply (from `on_error`) remains visible.
- On next bot start, `_recover_pending()` in `bot.py` walks `.pending` markers and retries transcription.

### Mood flow
- `send_mood_check` job posts inline keyboard at configured times (`MOOD_CHECK_TIMES`).
- `handle_mood_callback` writes to `storage/mood.csv` + diary, edits the message to a confirmation, then deletes it after `CONFIRM_TTL`.
- Expired callback queries (>~10 min — old keyboards the user taps late) are caught silently via `try/except` around `query.answer()`.

### Transcription backend
- `WhisperLocalService` invokes the `whisper.exe` / `whisper` CLI as a subprocess.
- VAD support: when `WHISPER_VAD=true`, passes `--vad --vad-model <path>` plus optional `--vad-threshold`, `--vad-min-silence-duration-ms`, `--vad-speech-pad-ms` flags to whisper.cpp (Silero VAD skips silent regions).
- Timeout: `WHISPER_TIMEOUT` env var, empty/0 means no limit (recommended on CPU).

## Key constraints

- Script targets Windows by default (whisper.exe, Windows paths) but runs cross-platform if `WHISPER_EXE` / `FFMPEG_EXE` are set appropriately.
- Diary files are **appended**, never overwritten.
- Bot must have "Delete messages" permission in the chat for history cleanup to work (default in private bot chats).
- The `TranscriptionWorker` is intentionally single-threaded — parallel whisper runs would thrash CPU.
- Long polling uses PTB defaults (`run_polling(drop_pending_updates=True)`). Do not add `poll_interval` — it only adds idle sleep on top of long-polling and increases callback latency.
