"""Stage-only E2E hook commands for live Happy Moment and Heist coverage.

These handlers are intentionally hidden from the Bot API command menu and must
only be included by the application when ``LEFT4CASINO_E2E_HOOKS_ENABLED`` is
explicitly true/1. They mutate live event state and are meant for staging E2E
tests, not production.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db import Database
from bot.services.happy_moment import HappyMomentService, HappyMomentTier, ScheduledMoment
from bot.services.heist import HeistService, HeistState

router = Router()
flags = {"throttling_key": "default"}

ENV_E2E_HOOKS_ENABLED = "LEFT4CASINO_E2E_HOOKS_ENABLED"
ENV_E2E_HOOKS_ALLOWED_USER_ID = "LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID"


def e2e_hooks_enabled(env: dict[str, str] | None = None) -> bool:
    value = (os.environ if env is None else env).get(ENV_E2E_HOOKS_ENABLED, "")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


async def _caller_allowed(message: Message, env: dict[str, str] | None = None) -> bool:
    if not message.from_user:
        return False
    raw_allowed = (os.environ if env is None else env).get(ENV_E2E_HOOKS_ALLOWED_USER_ID, "")
    if raw_allowed.strip() == "":
        return True
    try:
        allowed_user_id = int(raw_allowed)
    except ValueError:
        await message.answer("E2E hooks forbidden: invalid allowed user guard")
        return False
    if message.from_user.id != allowed_user_id:
        await message.answer("E2E hooks forbidden for this user")
        return False
    return True


@router.message(Command("e2e_happy_start"), flags=flags)
async def cmd_e2e_happy_start(
    message: Message,
    happy_moment_service: HappyMomentService,
    db: Database,
) -> None:
    if not await _caller_allowed(message):
        return
    if happy_moment_service.active_moment is not None:
        await happy_moment_service.end_moment()

    now = datetime.now(happy_moment_service.timezone)
    moment = ScheduledMoment(
        scheduled_time=now,
        tier=HappyMomentTier(duration_minutes=5, multiplier=2.0),
        name="E2E Happy Moment",
    )
    await db.upsert_scheduled_event(
        event_id=f"happy_moment_{moment.scheduled_time.isoformat()}",
        event_type="happy_moment_start",
        scheduled_at=moment.scheduled_time.isoformat(),
        timezone=str(happy_moment_service.timezone),
        source_date=now.date().isoformat(),
        status="scheduled",
        metadata=json.dumps(
            {
                "name": moment.name,
                "duration_minutes": moment.tier.duration_minutes,
                "multiplier": moment.tier.multiplier,
                "source": "e2e_hook",
            }
        ),
    )
    await happy_moment_service.start_moment(moment)
    await message.answer("E2E Happy Moment started: multiplier x2.0 for 5 minutes")


@router.message(Command("e2e_happy_end"), flags=flags)
async def cmd_e2e_happy_end(message: Message, happy_moment_service: HappyMomentService) -> None:
    if not await _caller_allowed(message):
        return
    await happy_moment_service.end_moment()
    await message.answer("E2E Happy Moment ended")


@router.message(Command("e2e_heist_start"), flags=flags)
async def cmd_e2e_heist_start(
    message: Message,
    heist_service: HeistService,
    db: Database,
) -> None:
    if not await _caller_allowed(message):
        return
    chat_id = message.chat.id
    if heist_service.is_active(chat_id):
        await heist_service.end_heist(chat_id)

    now = datetime.now(heist_service.timezone)
    state = HeistState(
        chat_id=chat_id,
        base_value=100,
        pot=0,
        pot_cap=1,
        seed_amount=1,
        phase="robbery",
        phase1_end=now + timedelta(minutes=5),
        phase2_end=None,
        phase2_duration=5,
        start_time=now,
    )
    heist_service.active_heists[chat_id] = state

    await db.add_event(
        str(uuid.uuid4()),
        0,
        "heist_start",
        0,
        json.dumps(
            {
                "chat_id": chat_id,
                "base_value": state.base_value,
                "pot_cap": state.pot_cap,
                "seed_amount": state.seed_amount,
                "phase1_duration_minutes": 5,
                "phase2_duration_minutes": state.phase2_duration,
                "source": "e2e_hook",
            }
        ),
        chat_id,
    )
    await heist_service.bot.send_message(
        chat_id,
        "🏦💥 <b>ОГРАБЛЕНИЕ БАНКА!</b> 💥🏦\n\n"
        "Сейф вскрыт! Крутите слоты — вся добыча идёт в общий котёл!\n"
        "Последний, кто крутанёт, заберёт ВСЁ! 💰\n\n"
        "<b>Правила:</b>\n"
        "• Проигрыши 🎰 идут в общий банк\n"
        "• Выигрыши забираете себе (как обычно)\n"
        "• Когда ограбление закончится — последний игрок забирает весь банк!",
    )
    await message.answer("E2E Heist started for this chat")


@router.message(Command("e2e_heist_end"), flags=flags)
async def cmd_e2e_heist_end(message: Message, heist_service: HeistService) -> None:
    if not await _caller_allowed(message):
        return
    await heist_service.end_heist(message.chat.id)
    await message.answer("E2E Heist ended for this chat")
