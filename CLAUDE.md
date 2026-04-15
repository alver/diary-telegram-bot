# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
python bot.py
```

Requires a `.env` file (see `.env.example`). Minimum vars: `BOT_TOKEN`, `ALLOWED_USER_IDS`, `DIARY_CHAT_ID`, `WHISPER_MODEL_PATH`, `WHISPER_EXE`. Optional: `FFMPEG_EXE`, `WHISPER_LANG`, `WHISPER_TIMEOUT`, `WHISPER_VAD`, `WHISPER_VAD_MODEL`, `MOOD_PING_TIMES`, `PING_WINDOW_MINUTES`, `MIN_GAP_BETWEEN_PINGS_MINUTES`, `RESPONSE_TIMEOUT_MINUTES`, `SLEEP_QUESTION_TIME`.

Dependencies: `python-telegram-bot[job-queue]`, `python-dotenv`. External binaries: `ffmpeg` and a whisper.cpp CLI build (e.g. `whisper.exe`). The legacy Pyrogram-based single-file pipeline lives under `old/` and is no longer maintained.

## Architecture

Event-driven Telegram bot built on `python-telegram-bot` v21, long-polling. Entry point `bot.py` wires handlers and a scheduled `JobQueue`.

### Packages
- `bot.py` — app bootstrap, handler registration, startup recovery, scheduler wiring.
- `config.py` — all settings loaded from `.env`.
- `handlers/messages.py` — text / voice / audio message handling.
- `handlers/mood.py` — 2-D mood (valence + arousal) keyboard, callback, per-ping state, timeout expiry.
- `handlers/sleep.py` — daily PSQI-1 sleep-quality prompt, callback, timeout expiry.
- `handlers/scheduler.py` — randomized daily mood-ping planner.
- `services/audio.py` — ffmpeg WAV/MP3 conversion, pending-file tracking, archive path helpers.
- `services/diary.py` — append to daily `YYYY-MM-DD.md` files and to the mood / sleep CSVs.
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

### Mood flow (2-D: valence + arousal, circumplex model)
- `handlers/scheduler.py` plans one `run_once` job per base time in `MOOD_PING_TIMES`, each at a random offset in ±`PING_WINDOW_MINUTES`. Offsets are re-rolled if any adjacent pair is closer than `MIN_GAP_BETWEEN_PINGS_MINUTES`; after 50 failed attempts it clamps. `schedule_initial()` plans today's remaining pings at startup and installs a daily planner job at 00:05 to re-plan each day.
- `send_mood_check` posts a single message with a two-column inline keyboard (pleasantness 1–5 left, energy 1–5 right; header row uses `noop:0` callbacks). Callback data: `val:{entry_id}:{n}` and `aro:{entry_id}:{n}`, where `entry_id = "m" + YYYYMMDDHHMMSS`.
- Per-ping state lives in `context.bot_data["pending_mood_pings"][entry_id]` as a `PendingMood` dataclass. Tapping a button in a column replaces any prior selection there and re-renders the keyboard with a ✅ prefix on the active choice.
- Finalization: once both `valence` and `arousal` are set, the entry is appended to `storage/mood_entries.csv` (status `complete`), the message is edited to the confirmation and deleted after `CONFIRM_TTL` (5s).
- Timeout: a `run_once` expiry job fires `RESPONSE_TIMEOUT_MINUTES` after send. If the entry is still pending, it's saved with status `partial` (one scale picked) or `missed` (neither), and the message is edited to an expired-notice (removes the keyboard). Late taps on a no-longer-pending entry trigger a `show_alert` "prompt expired" toast.
- Expired callback queries (>~10 min — old keyboards the user taps late) are still caught silently via `try/except` around `query.answer()` as a defensive layer.

### Sleep flow (PSQI component 1)
- `send_sleep_check` runs daily at `SLEEP_QUESTION_TIME` (not randomized — it's a morning anchor). The prompt has 4 buttons (`1` Very good … `4` Very bad), callback data `slp:{entry_id}:{n}`, `entry_id = "s" + YYYYMMDDHHMMSS`.
- `night_of` is set to the date one day before `prompt_sent_at` (the night ending that morning).
- Same timeout model as mood: `RESPONSE_TIMEOUT_MINUTES`, status `complete` / `missed`, late taps rejected with an alert.
- Entries are appended to `storage/sleep.csv` and to the daily markdown.

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
- Pending mood / sleep ping state is in-memory (`bot_data`). A bot restart loses any in-flight prompts — the associated timeout jobs are also lost, so no `missed` row is written for those. Acceptable trade-off; persisting this across restarts is not a goal.
- Mood ping randomization and gap-enforcement live in `_randomize_times()` in `handlers/scheduler.py`. With the defaults (base times 6 h apart, ±90 min window, 120 min min-gap) the constraint is trivially satisfied; the retry/clamp path exists so that tightening parameters can't silently schedule overlapping pings.
