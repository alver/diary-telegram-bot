import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

import config
from services import diary as diary_svc

CONFIRM_TTL = 3  # seconds to keep the "Mood recorded" confirmation visible

logger = logging.getLogger(__name__)

# level → (label, keyboard display)
MOOD_LEVELS: dict[int, tuple[str, str]] = {
    5: ("Great",   "😄 Great"),
    4: ("Good",    "🙂 Good"),
    3: ("Neutral", "😐 Neutral"),
    2: ("Low",     "😕 Low"),
    1: ("Bad",     "😞 Bad"),
}

MOOD_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton(display, callback_data=f"mood:{level}")]
        for level, (_label, display) in sorted(MOOD_LEVELS.items(), reverse=True)
    ]
)


async def send_mood_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: send the mood check-in keyboard to the configured diary chat."""
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text="How are you feeling right now?",
        reply_markup=MOOD_KEYBOARD,
    )


async def handle_mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        # Callback query expired (>10 min old) — log and bail out silently.
        logger.warning("Mood callback query expired; ignoring tap on old keyboard")
        return

    # Enforce the allow-list for button taps (CallbackQueryHandler doesn't take filters).
    if config.ALLOWED_USER_IDS and update.effective_user.id not in config.ALLOWED_USER_IDS:
        return

    if not query.data or not query.data.startswith("mood:"):
        return

    try:
        level = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return

    entry = MOOD_LEVELS.get(level)
    if entry is None:
        return
    label, _display = entry

    timestamp = diary_svc.now()
    diary_svc.append_mood(timestamp, level, label)

    await query.edit_message_text(
        f"Mood recorded: {label} ({level}/5) at {timestamp.strftime('%H:%M')}"
    )
    logger.info("Mood recorded: level=%d label=%s", level, label)

    asyncio.create_task(_delete_later(query.message))


async def _delete_later(msg: Message, delay: int = CONFIRM_TTL) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        logger.debug("Mood message delete failed", exc_info=True)
