# Diary Bot

A personal Telegram bot that acts as a daily diary. Send it text notes, voice messages, or audio files and they are saved as daily Markdown files. The bot also periodically asks about your mood and tracks the data for later analysis.

---

## Features

- **Text messages** → appended to `storage/diary/YYYY-MM-DD.md`
- **Voice & audio messages** → downloaded, converted to 16 kHz mono WAV via ffmpeg, transcribed with whisper.cpp, then saved to the diary
- **Archive copies** → 32 kbps MP3 of every audio file saved to `storage/archive/` (the filename referenced from the diary)
- **Clean chat** → after successful processing the bot deletes the user's message and its own replies, keeping the chat at zero items
- **Crash recovery** → audio left mid-transcription is retried on the next start via `.pending` markers
- **Mood check-ins** → inline keyboard (Great / Good / Neutral / Low / Bad) sent on a configurable schedule; responses saved to the diary and to `storage/mood.csv` for analysis
- **Silero VAD (optional)** → whisper.cpp skips silent regions for large speedups on diary-style recordings with long pauses
- **Modular transcription** → drop in a new backend under `services/transcription/` without touching anything else

---

## Requirements

| Tool | Notes |
|---|---|
| Python 3.11+ | Tested on 3.11 / 3.12 |
| ffmpeg | On `PATH`, or set `FFMPEG_EXE` to an absolute path |
| whisper.cpp binary | The `whisper.exe` / `whisper` ggml CLI build |
| A ggml model file | e.g. `ggml-large-v3-q5_0.bin` from [ggerganov/whisper.cpp releases](https://github.com/ggerganov/whisper.cpp/releases) |
| Silero VAD model (optional) | `ggml-silero-v6.2.0.bin` — fetch via `./models/download-vad-model.sh silero-v6.2.0` in the whisper.cpp tree |

---

## Installation

```bash
# 1. Clone / copy this directory
cd diary_bot

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Copy and fill in the environment file
cp .env.example .env
# Edit .env — at minimum set BOT_TOKEN, ALLOWED_USER_IDS, DIARY_CHAT_ID,
# WHISPER_MODEL_PATH, and WHISPER_EXE
```

### Getting a bot token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the token into `BOT_TOKEN` in `.env`

### Finding your Telegram user ID

Message [@userinfobot](https://t.me/userinfobot) — it replies with your numeric user ID. Put this in both `ALLOWED_USER_IDS` and `DIARY_CHAT_ID`.

---

## Running

```bash
python bot.py
```

The bot uses long-polling, so no public URL or webhook is needed.

To keep it running persistently on a server, wrap it in systemd, supervisord, screen, or tmux.

### Example systemd unit

```ini
[Unit]
Description=Diary Telegram Bot
After=network.target

[Service]
WorkingDirectory=/path/to/diary_bot
ExecStart=/path/to/diary_bot/.venv/bin/python bot.py
Restart=on-failure
EnvironmentFile=/path/to/diary_bot/.env

[Install]
WantedBy=multi-user.target
```

---

## Configuration reference

All variables live in `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot token from @BotFather |
| `ALLOWED_USER_IDS` | empty (anyone) | Comma-separated user IDs allowed to interact |
| `DIARY_CHAT_ID` | — | Chat that receives scheduled mood check-ins |
| `AUDIO_DIR` / `ARCHIVE_DIR` / `DIARY_DIR` / `MOOD_CSV` | `storage/...` | Output paths |
| `TRANSCRIPTION_SERVICE` | `whisper_local` | Backend name registered in `services/transcription/__init__.py` |
| `WHISPER_MODEL_PATH` | — | Path to a ggml model file |
| `WHISPER_EXE` | `whisper` | whisper.cpp CLI binary (use `whisper.exe` on Windows) |
| `WHISPER_LANG` | `ru` | Language code passed via `-l` |
| `WHISPER_TIMEOUT` | empty (no limit) | Max seconds per whisper run — leave empty on CPU |
| `FFMPEG_EXE` | `ffmpeg` | ffmpeg binary; set an absolute path if not on PATH |
| `WHISPER_VAD` | `false` | Enable Silero VAD in whisper.cpp |
| `WHISPER_VAD_MODEL` | — | Path to the VAD model (required when `WHISPER_VAD=true`) |
| `WHISPER_VAD_THRESHOLD` / `WHISPER_VAD_MIN_SILENCE_MS` / `WHISPER_VAD_SPEECH_PAD_MS` | empty (whisper defaults) | Optional VAD tunables |
| `MOOD_CHECK_TIMES` | `09:00,15:00,21:00` | Comma-separated 24h local times for mood prompts |

---

## Project structure

```
diary_bot/
├── bot.py                          # Entry point — app setup, handler registration, scheduler
├── config.py                       # All settings loaded from .env
├── handlers/
│   ├── messages.py                 # Incoming text / voice / audio
│   └── mood.py                     # Mood keyboard, callback, scheduled job
├── services/
│   ├── audio.py                    # ffmpeg conversion, archive, path helpers
│   ├── diary.py                    # Append to .md files and mood.csv
│   └── transcription/
│       ├── base.py                 # TranscriptionService ABC
│       ├── whisper_local.py        # Local whisper.cpp backend
│       └── __init__.py             # Factory: get_transcription_service()
├── storage/                        # Created at runtime
│   ├── audio/                      # Transient: originals + .pending markers (cleared on success)
│   ├── archive/                    # 32 kbps MP3 copies — long-term, referenced from the diary
│   ├── diary/                      # YYYY-MM-DD.md files
│   └── mood.csv                    # Mood time-series
├── requirements.txt
├── .env.example
└── README.md
```

---

## Diary format

Each daily file looks like:

```markdown
---

**2026-04-14 09:03**

Had a good meeting this morning.

---

**2026-04-14 09:15**

**Mood check-in:** Great (5/5)

---

**2026-04-14 11:42**

*[Audio: 20260414_114200.mp3]*

This is the transcribed text of the voice message.
```

The filename points at the 32 kbps archive MP3 in `storage/archive/`. The original download and intermediate WAV are removed after successful transcription.

---

## Mood data (`storage/mood.csv`)

```
timestamp,level,label
2026-04-14T09:15:32,5,Great
2026-04-14T15:01:10,3,Neutral
```

This CSV is ready to load into pandas, a spreadsheet, or any analysis tool to look for patterns, periodicity, good/bad zones, etc.

---

## Adding a new transcription backend

1. Create `services/transcription/my_service.py` with a class that extends `TranscriptionService` and implements `transcribe(wav_path: str) -> str`.
2. Register it in `services/transcription/__init__.py`'s `get_transcription_service()` factory.
3. Set `TRANSCRIPTION_SERVICE=my_service` in `.env`.

Planned backends (not yet implemented):

- `openai_whisper` — OpenAI Whisper API
- `faster_whisper` — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local, GPU-accelerated)
- `whisper_python` — openai-whisper Python package

---

## What comes next

- **Mood analysis script** — load `mood.csv`, detect trends and periodicity, plot charts
- **Weekly/monthly diary summary** — aggregate entries and send a recap via the bot
- **Search command** — `/search <keyword>` over diary Markdown files
- **Export command** — send a ZIP of all diary files on demand
