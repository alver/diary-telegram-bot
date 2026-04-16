"""Randomized mood-ping scheduler.

For each configured base time, the actual ping fires at a random offset
within ±PING_WINDOW_MINUTES. Offsets are chosen once per day (stable but
unpredictable) and re-rolled if two adjacent pings would be closer than
MIN_GAP_BETWEEN_PINGS_MINUTES.

The sleep question is scheduled separately at a fixed time (not randomized).
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta

from telegram.ext import Application, ContextTypes

import config
from handlers.mood import send_mood_check

logger = logging.getLogger(__name__)

_PLANNER_JOB_NAME_PREFIX = "mood-ping-"
_MAX_RANDOMIZATION_ATTEMPTS = 50


def _randomize_times(base_times: list[time], day: datetime) -> list[datetime]:
    """Return one concrete datetime per base time, on `day`, with random
    offsets in [-window, +window] minutes, enforcing the minimum gap
    between adjacent pings."""
    window = config.PING_WINDOW_MINUTES
    min_gap = timedelta(minutes=config.MIN_GAP_BETWEEN_PINGS_MINUTES)
    tz = day.tzinfo

    def draw() -> list[datetime]:
        out = []
        for t in base_times:
            base = datetime.combine(day.date(), t).replace(tzinfo=tz)
            offset = random.uniform(-window, window)
            out.append(base + timedelta(minutes=offset))
        return sorted(out)

    for attempt in range(_MAX_RANDOMIZATION_ATTEMPTS):
        candidates = draw()
        ok = all(
            (candidates[i] - candidates[i - 1]) >= min_gap
            for i in range(1, len(candidates))
        )
        if ok:
            return candidates

    # Fallback: take the draw and clamp gaps by pushing later pings forward.
    logger.warning(
        "Could not satisfy min_gap=%s after %d attempts; clamping.",
        min_gap, _MAX_RANDOMIZATION_ATTEMPTS,
    )
    candidates = draw()
    for i in range(1, len(candidates)):
        earliest = candidates[i - 1] + min_gap
        if candidates[i] < earliest:
            candidates[i] = earliest
    return candidates


def _clear_today_ping_jobs(application: Application) -> None:
    for job in application.job_queue.jobs():
        if job.name and job.name.startswith(_PLANNER_JOB_NAME_PREFIX):
            job.schedule_removal()


def _plan_day(application: Application, chat_id: int, now: datetime) -> None:
    if not config.MOOD_CHECK_TIMES:
        return

    _clear_today_ping_jobs(application)

    scheduled = _randomize_times(config.MOOD_CHECK_TIMES, now)
    count = 0
    for fire_at in scheduled:
        if fire_at <= now:
            # Skip pings whose randomized time already passed (e.g. bot
            # started mid-day, or planner ran a little late).
            continue
        application.job_queue.run_once(
            send_mood_check,
            when=fire_at,
            chat_id=chat_id,
            name=f"{_PLANNER_JOB_NAME_PREFIX}{fire_at.strftime('%Y%m%d%H%M%S')}",
        )
        count += 1

    logger.info(
        "Planned %d mood ping(s) for %s: %s",
        count,
        now.date().isoformat(),
        ", ".join(t.strftime("%H:%M:%S") for t in scheduled),
    )


async def daily_planner_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs shortly after midnight each day to plan that day's pings."""
    chat_id = context.job.chat_id
    _plan_day(context.application, chat_id, datetime.now().astimezone())


def schedule_initial(application: Application, chat_id: int) -> None:
    """Plan today's remaining pings and register the daily planner job."""
    now = datetime.now().astimezone()
    _plan_day(application, chat_id, now)

    # Re-plan at 00:05 every day.
    application.job_queue.run_daily(
        daily_planner_job,
        time=time(0, 5, tzinfo=now.tzinfo),
        chat_id=chat_id,
        name="mood-daily-planner",
    )
