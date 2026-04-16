import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from services import diary as diary_svc

logger = logging.getLogger(__name__)

CONFIRM_TTL = 5  # seconds to keep the final confirmation visible before deletion

PLEASANTNESS_LABELS = {
    5: "😄 Very pleasant",
    4: "🙂 Pleasant",
    3: "😐 Neutral",
    2: "😕 Unpleasant",
    1: "😞 Very unpleasant",
}
ENERGY_LABELS = {
    5: "⚡ Very high",
    4: "🔥 High",
    3: "➖ Medium",
    2: "🧘 Low",
    1: "😴 Very low",
}

PROMPT_TEXT = (
    "How are you feeling right now?\n\n"
    "Pick one from each column — pleasantness on the left, energy on the right."
)
NOOP_CB = "noop:0"


@dataclass
class PendingMood:
    entry_id: str
    chat_id: int
    message_id: int
    pleasantness: int | None = None
    energy: int | None = None
    timeout_job: object | None = field(default=None, repr=False)


def _pending_store(context: ContextTypes.DEFAULT_TYPE) -> dict[str, PendingMood]:
    return context.bot_data.setdefault("pending_mood_pings", {})


def _build_keyboard(entry_id: str, pleasantness: int | None, energy: int | None) -> InlineKeyboardMarkup:
    def mark(label: str, selected: bool) -> str:
        return f"✅ {label}" if selected else label

    rows = [[
        InlineKeyboardButton("Pleasantness", callback_data=NOOP_CB),
        InlineKeyboardButton("Energy", callback_data=NOOP_CB),
    ]]
    for n in range(5, 0, -1):
        rows.append([
            InlineKeyboardButton(
                mark(PLEASANTNESS_LABELS[n], pleasantness == n),
                callback_data=f"pls:{entry_id}:{n}",
            ),
            InlineKeyboardButton(
                mark(ENERGY_LABELS[n], energy == n),
                callback_data=f"nrg:{entry_id}:{n}",
            ),
        ])
    return InlineKeyboardMarkup(rows)


async def send_mood_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue entry point: send a 2-D mood prompt and arm a response timeout."""
    await _send_mood_prompt(context, context.job.chat_id)


async def _send_mood_prompt(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    entry_id = diary_svc.now().strftime("m%Y%m%d%H%M%S")

    markup = _build_keyboard(entry_id, None, None)
    message = await context.bot.send_message(chat_id=chat_id, text=PROMPT_TEXT, reply_markup=markup)

    pending = PendingMood(
        entry_id=entry_id,
        chat_id=chat_id,
        message_id=message.message_id,
    )
    _pending_store(context)[entry_id] = pending

    timeout_job = context.job_queue.run_once(
        _expire_mood,
        when=config.RESPONSE_TIMEOUT_MINUTES * 60,
        data={"entry_id": entry_id, "chat_id": chat_id},
        name=f"mood-timeout-{entry_id}",
    )
    pending.timeout_job = timeout_job
    logger.info("Mood prompt sent: entry_id=%s timeout=%dm", entry_id, config.RESPONSE_TIMEOUT_MINUTES)


async def handle_mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Mood callback query expired; ignoring tap on old keyboard")
        return

    if config.ALLOWED_USER_IDS and update.effective_user.id not in config.ALLOWED_USER_IDS:
        return

    data = query.data or ""
    if data.startswith("noop:"):
        return

    parts = data.split(":")
    if len(parts) != 3 or parts[0] not in {"pls", "nrg"}:
        return
    kind, entry_id, raw = parts
    try:
        value = int(raw)
    except ValueError:
        return
    if value not in range(1, 6):
        return

    store = _pending_store(context)
    pending = store.get(entry_id)
    if pending is None:
        # Timed out or unknown — prompt is no longer answerable.
        try:
            await query.answer("This mood prompt has expired.", show_alert=True)
        except Exception:
            pass
        return

    if kind == "pls":
        pending.pleasantness = value
    else:
        pending.energy = value

    if pending.pleasantness is not None and pending.energy is not None:
        await _finalize_complete(context, pending)
        return

    # Partial: update keyboard to show the current selection.
    try:
        await query.edit_message_reply_markup(
            reply_markup=_build_keyboard(entry_id, pending.pleasantness, pending.energy)
        )
    except Exception:
        logger.debug("Failed to refresh mood keyboard", exc_info=True)


async def _finalize_complete(context: ContextTypes.DEFAULT_TYPE, pending: PendingMood) -> None:
    diary_svc.append_mood_entry(
        entry_id=pending.entry_id,
        timestamp=diary_svc.now(),
        pleasantness=pending.pleasantness,
        energy=pending.energy,
        status="complete",
    )
    _pending_store(context).pop(pending.entry_id, None)
    if pending.timeout_job is not None:
        try:
            pending.timeout_job.schedule_removal()
        except Exception:
            pass

    try:
        await context.bot.edit_message_text(
            chat_id=pending.chat_id,
            message_id=pending.message_id,
            text=(
                f"Recorded: pleasantness {pending.pleasantness}/5, "
                f"energy {pending.energy}/5 ✓"
            ),
        )
    except Exception:
        logger.debug("Failed to edit mood prompt to confirmation", exc_info=True)

    logger.info(
        "Mood recorded: entry_id=%s pleasantness=%d energy=%d",
        pending.entry_id, pending.pleasantness, pending.energy,
    )

    asyncio.create_task(_delete_message_later(context, pending.chat_id, pending.message_id))


async def _expire_mood(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    entry_id = data.get("entry_id")
    chat_id = data.get("chat_id")
    pending = _pending_store(context).pop(entry_id, None)
    if pending is None:
        return

    has_any = pending.pleasantness is not None or pending.energy is not None
    status = "partial" if has_any else "missed"

    diary_svc.append_mood_entry(
        entry_id=pending.entry_id,
        timestamp=diary_svc.now(),
        pleasantness=pending.pleasantness,
        energy=pending.energy,
        status=status,
    )

    note = "⌛ Mood window expired." + (
        f" Saved partial: "
        f"pleasantness={pending.pleasantness or '—'}, energy={pending.energy or '—'}"
        if has_any else " No response recorded."
    )
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=pending.message_id, text=note)
    except Exception:
        logger.debug("Failed to edit expired mood prompt", exc_info=True)

    logger.info("Mood prompt expired: entry_id=%s status=%s", entry_id, status)


async def _delete_message_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(CONFIRM_TTL)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("Mood confirmation delete failed", exc_info=True)


# ---------- /mood manual trigger ----------

async def cmd_mood_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual /mood command — sends a prompt to the current chat using the same flow."""
    await _send_mood_prompt(context, update.effective_chat.id)
    try:
        await update.message.delete()
    except Exception:
        pass
