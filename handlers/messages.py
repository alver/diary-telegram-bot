import asyncio
import logging
import os
from typing import Any, Iterable

from telegram import Message, Update
from telegram.ext import ContextTypes

from services import audio as audio_svc
from services import diary as diary_svc
from services.transcription.worker import TranscriptionWorker

logger = logging.getLogger(__name__)

# Seconds to keep confirmation messages visible before deletion.
CONFIRM_TTL = 3


def _worker(context: ContextTypes.DEFAULT_TYPE) -> TranscriptionWorker:
    return context.bot_data["transcription_worker"]


async def _delete_later(messages: Iterable[Message], delay: int = CONFIRM_TTL) -> None:
    await asyncio.sleep(delay)
    for m in messages:
        try:
            await m.delete()
        except Exception:
            logger.debug("Message delete failed (already gone?)", exc_info=True)


def _schedule_cleanup(*messages: Message, delay: int = CONFIRM_TTL) -> None:
    asyncio.create_task(_delete_later(messages, delay))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    timestamp = diary_svc.to_local(msg.date)
    diary_svc.append_text(timestamp, msg.text)
    reply = await msg.reply_text("Saved to diary.")
    _schedule_cleanup(msg, reply)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_media(update, context, update.message.voice, default_ext="ogg")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_media(update, context, update.message.audio, default_ext="mp3")


async def _handle_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_obj: Any,
    default_ext: str,
) -> None:
    msg = update.message
    timestamp = diary_svc.to_local(msg.date)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

    ext = default_ext
    filename_attr = getattr(file_obj, "file_name", None)
    if filename_attr:
        _, detected = os.path.splitext(filename_attr)
        if detected:
            ext = detected.lstrip(".")

    save_path = audio_svc.audio_save_path(timestamp_str, file_obj.file_id[:16], ext)
    tg_file = await context.bot.get_file(file_obj.file_id)
    await tg_file.download_to_drive(save_path)
    audio_svc.mark_pending(save_path)
    logger.info("Audio saved: %s", save_path)

    progress = await msg.reply_text("Saved. Transcribing...")
    try:
        transcript = await _worker(context).transcribe_file(save_path)
        mp3_path = audio_svc.archive_mp3_path(timestamp_str)
        diary_svc.append_audio(timestamp, transcript, mp3_path)
        audio_svc.cleanup_processed(save_path)
        done = await msg.reply_text(f"Transcript saved:\n\n{transcript[:400]}")
        _schedule_cleanup(msg, progress, done)
    except Exception:
        # Audio is safe on disk (startup recovery will retry). Clear the
        # voice + progress note so only the error notice remains in chat.
        logger.exception("Transcription pipeline failed for %s", save_path)
        for m in (msg, progress):
            try:
                await m.delete()
            except Exception:
                logger.debug("Cleanup delete failed on error path", exc_info=True)
        raise
