import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from services import diary as diary_svc

logger = logging.getLogger(__name__)

CONFIRM_TTL = 5

# PSQI component 1 — subjective sleep quality (validated 4-point scale).
SLEEP_LABELS: dict[int, str] = {
    1: "Very good",
    2: "Fairly good",
    3: "Fairly bad",
    4: "Very bad",
}

PROMPT_TEXT = "How would you rate your sleep quality last night?"


@dataclass
class PendingSleep:
    entry_id: str
    chat_id: int
    message_id: int
    prompt_sent_at: datetime
    night_of: "datetime.date"  # noqa
    timeout_job: object | None = field(default=None, repr=False)


def _pending_store(context: ContextTypes.DEFAULT_TYPE) -> dict[str, PendingSleep]:
    return context.bot_data.setdefault("pending_sleep_pings", {})


def _keyboard(entry_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"{n} — {label}", callback_data=f"slp:{entry_id}:{n}")]
         for n, label in SLEEP_LABELS.items()]
    )


async def send_sleep_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_sleep_prompt(context, context.job.chat_id)


async def _send_sleep_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    prompt_sent_at = diary_svc.now()
    night_of = (prompt_sent_at - timedelta(days=1)).date()
    entry_id = prompt_sent_at.strftime("s%Y%m%d%H%M%S")

    message = await context.bot.send_message(
        chat_id=chat_id,
        text=PROMPT_TEXT,
        reply_markup=_keyboard(entry_id),
    )

    pending = PendingSleep(
        entry_id=entry_id,
        chat_id=chat_id,
        message_id=message.message_id,
        prompt_sent_at=prompt_sent_at,
        night_of=night_of,
    )
    _pending_store(context)[entry_id] = pending

    timeout_job = context.job_queue.run_once(
        _expire_sleep,
        when=config.RESPONSE_TIMEOUT_MINUTES * 60,
        data={"entry_id": entry_id, "chat_id": chat_id},
        name=f"sleep-timeout-{entry_id}",
    )
    pending.timeout_job = timeout_job
    logger.info("Sleep prompt sent: entry_id=%s night_of=%s", entry_id, night_of)


async def handle_sleep_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Sleep callback query expired; ignoring old tap")
        return

    if config.ALLOWED_USER_IDS and update.effective_user.id not in config.ALLOWED_USER_IDS:
        return

    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "slp":
        return
    _, entry_id, raw = parts
    try:
        quality = int(raw)
    except ValueError:
        return
    if quality not in SLEEP_LABELS:
        return

    pending = _pending_store(context).pop(entry_id, None)
    if pending is None:
        try:
            await query.answer("This sleep prompt has expired.", show_alert=True)
        except Exception:
            pass
        return

    if pending.timeout_job is not None:
        try:
            pending.timeout_job.schedule_removal()
        except Exception:
            pass

    responded_at = diary_svc.now()
    diary_svc.append_sleep_entry(
        entry_id=pending.entry_id,
        prompt_sent_at=pending.prompt_sent_at,
        responded_at=responded_at,
        night_of=pending.night_of,
        sleep_quality=quality,
        status="complete",
    )

    try:
        await query.edit_message_text(
            f"Sleep recorded: {SLEEP_LABELS[quality]} ({quality}/4) ✓"
        )
    except Exception:
        logger.debug("Failed to edit sleep prompt to confirmation", exc_info=True)

    logger.info("Sleep recorded: entry_id=%s quality=%d", entry_id, quality)
    asyncio.create_task(_delete_later(context, pending.chat_id, pending.message_id))


async def _expire_sleep(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    entry_id = data.get("entry_id")
    chat_id = data.get("chat_id")
    pending = _pending_store(context).pop(entry_id, None)
    if pending is None:
        return

    diary_svc.append_sleep_entry(
        entry_id=pending.entry_id,
        prompt_sent_at=pending.prompt_sent_at,
        responded_at=None,
        night_of=pending.night_of,
        sleep_quality=None,
        status="missed",
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=pending.message_id,
            text="⌛ Sleep question expired. No response recorded.",
        )
    except Exception:
        logger.debug("Failed to edit expired sleep prompt", exc_info=True)
    logger.info("Sleep prompt expired: entry_id=%s", entry_id)


async def _delete_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(CONFIRM_TTL)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("Sleep confirmation delete failed", exc_info=True)
