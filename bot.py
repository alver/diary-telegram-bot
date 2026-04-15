import asyncio
import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from handlers.messages import handle_audio, handle_text, handle_voice
from handlers.mood import MOOD_KEYBOARD, handle_mood_callback, send_mood_check
from services import audio as audio_svc
from services import diary as diary_svc
from services.transcription import get_transcription_service
from services.transcription.worker import TranscriptionWorker

# ==============
# Logging Setup
# ==============

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("diary_bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ================
# Command handlers
# ================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Diary bot is running.\n\n"
        "Send me:\n"
        "• A text message → saved to today's diary\n"
        "• A voice message → transcribed and saved\n"
        "• An audio file → transcribed and saved\n\n"
        "I will also ask about your mood periodically."
    )


async def cmd_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "How are you feeling right now?",
        reply_markup=MOOD_KEYBOARD,
    )
    # Drop the /mood command itself — the keyboard is deleted after a tap.
    try:
        await update.message.delete()
    except Exception:
        logger.debug("Could not delete /mood command message", exc_info=True)


# ==============
# Error handler
# ==============

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while handling update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"⚠️ Something went wrong: {type(context.error).__name__}: {context.error}"
            )
        except Exception:
            logger.exception("Failed to notify user of error")


# =======================
# Startup / shutdown hooks
# =======================

async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "About this bot"),
        BotCommand("mood",  "Manual mood check-in"),
    ])
    await _recover_pending(application)


async def _recover_pending(application: Application) -> None:
    """Re-run transcription for any audio files left in a pending state from a previous run."""
    pending = audio_svc.list_pending()
    if not pending:
        return

    logger.warning("Recovering %d interrupted transcription(s)", len(pending))
    worker: TranscriptionWorker = application.bot_data["transcription_worker"]

    for path in pending:
        timestamp = audio_svc.timestamp_from_filename(path) or diary_svc.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        try:
            transcript = await worker.transcribe_file(path)
            mp3_path = audio_svc.archive_mp3_path(timestamp_str)
            diary_svc.append_audio(timestamp, transcript, mp3_path)
            audio_svc.cleanup_processed(path)
            logger.info("Recovered transcription for %s", path)
        except Exception:
            logger.exception("Recovery failed for %s — leaving pending marker in place", path)


async def _post_shutdown(application: Application) -> None:
    worker = application.bot_data.get("transcription_worker")
    if worker is not None:
        worker.shutdown()


# =============
# App bootstrap
# =============

def main() -> None:
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Add it to your .env file.")
        sys.exit(1)

    # Build transcription worker eagerly — fail fast on misconfiguration
    # rather than on the first voice message.
    try:
        transcription_service = get_transcription_service()
    except Exception:
        logger.exception("Failed to initialize transcription service")
        sys.exit(1)
    worker = TranscriptionWorker(transcription_service)

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["transcription_worker"] = worker

    # Allow-list: applied as a PTB filter at registration time.
    user_filter = (
        filters.User(user_id=config.ALLOWED_USER_IDS)
        if config.ALLOWED_USER_IDS
        else filters.ALL
    )

    # Commands
    app.add_handler(CommandHandler("start", cmd_start, filters=user_filter))
    app.add_handler(CommandHandler("mood",  cmd_mood,  filters=user_filter))

    # Message handlers
    app.add_handler(MessageHandler(filters.VOICE & user_filter, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO & user_filter, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, handle_text))

    # Mood button callbacks (CallbackQueryHandler enforces allow-list internally)
    app.add_handler(CallbackQueryHandler(handle_mood_callback, pattern=r"^mood:"))

    # Error handler
    app.add_error_handler(on_error)

    # Schedule periodic mood checks
    if config.DIARY_CHAT_ID and config.MOOD_CHECK_TIMES:
        for check_time in config.MOOD_CHECK_TIMES:
            app.job_queue.run_daily(
                send_mood_check,
                time=check_time,
                chat_id=config.DIARY_CHAT_ID,
            )
        logger.info(
            "Mood checks scheduled at: %s",
            ", ".join(t.strftime("%H:%M") for t in config.MOOD_CHECK_TIMES),
        )
    else:
        logger.warning(
            "Mood checks not scheduled — set DIARY_CHAT_ID and MOOD_CHECK_TIMES in .env"
        )

    # Python 3.14 removed implicit event-loop creation; PTB v21's run_polling
    # still calls asyncio.get_event_loop(). Pre-create one so it works on 3.14.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    logger.info("Starting diary bot (long polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
