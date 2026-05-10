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

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.db import Database
from bot.services.happy_moment import HappyMomentService, HappyMomentTier, ScheduledMoment
from bot.services.heist import HeistService, HeistState

router = Router()
flags = {"throttling_key": "default"}
logger = structlog.get_logger()

ENV_E2E_HOOKS_ENABLED = "LEFT4CASINO_E2E_HOOKS_ENABLED"
ENV_E2E_HOOKS_ALLOWED_USER_ID = "LEFT4CASINO_E2E_HOOKS_ALLOWED_USER_ID"
E2E_HAPPY_NAME = "E2E Happy Moment"
E2E_SOURCE = "e2e_hook"


def e2e_hooks_enabled(env: dict[str, str] | None = None) -> bool:
    env_data = os.environ if env is None else env
    value = env_data.get(ENV_E2E_HOOKS_ENABLED, "")
    if value.strip().lower() not in {"1", "true", "yes", "y", "on"}:
        return False
    raw_allowed = env_data.get(ENV_E2E_HOOKS_ALLOWED_USER_ID, "")
    try:
        allowed_user_id = int(raw_allowed)
    except (TypeError, ValueError):
        logger.error(
            "E2E hooks enabled but caller guard is missing or invalid; hooks disabled",
            env_enabled=ENV_E2E_HOOKS_ENABLED,
            env_allowed_user=ENV_E2E_HOOKS_ALLOWED_USER_ID,
        )
        return False
    if allowed_user_id <= 0:
        logger.error(
            "E2E hooks enabled but caller guard must be a positive user id; hooks disabled",
            env_allowed_user=ENV_E2E_HOOKS_ALLOWED_USER_ID,
        )
        return False
    return True


async def _caller_allowed(message: Message, env: dict[str, str] | None = None) -> bool:
    if not message.from_user:
        return False
    raw_allowed = (os.environ if env is None else env).get(ENV_E2E_HOOKS_ALLOWED_USER_ID, "")
    try:
        allowed_user_id = int(raw_allowed)
    except ValueError:
        await message.answer("E2E hooks forbidden: missing or invalid allowed user guard")
        return False
    if allowed_user_id <= 0:
        await message.answer("E2E hooks forbidden: missing or invalid allowed user guard")
        return False
    if message.from_user.id != allowed_user_id:
        await message.answer("E2E hooks forbidden for this user")
        return False
    return True


def _is_e2e_happy_active(happy_moment_service: HappyMomentService) -> bool:
    active = happy_moment_service.active_moment
    return bool(active and (getattr(active, "e2e_owned", False) or active.name == E2E_HAPPY_NAME))


def _is_e2e_heist_state(state: HeistState | None) -> bool:
    return bool(state and getattr(state, "e2e_owned", False))


@router.message(Command("e2e_happy_start"), flags=flags)
async def cmd_e2e_happy_start(
    message: Message,
    happy_moment_service: HappyMomentService,
    db: Database,
) -> None:
    if not await _caller_allowed(message):
        return
    if happy_moment_service.active_moment is not None:
        if not _is_e2e_happy_active(happy_moment_service):
            await message.answer("E2E_HOOK_REFUSED happy_start non-E2E Happy Moment is active")
            return
        await happy_moment_service.end_moment()

    now = datetime.now(happy_moment_service.timezone)
    moment = ScheduledMoment(
        scheduled_time=now,
        tier=HappyMomentTier(duration_minutes=5, multiplier=2.0),
        name=E2E_HAPPY_NAME,
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
                "source": E2E_SOURCE,
            }
        ),
    )
    await happy_moment_service.start_moment(moment)
    if happy_moment_service.active_moment is not None:
        happy_moment_service.active_moment.e2e_owned = True
    await message.answer("E2E_HOOK_OK happy_start multiplier x2.0 for 5 minutes")


@router.message(Command("e2e_happy_end"), flags=flags)
async def cmd_e2e_happy_end(message: Message, happy_moment_service: HappyMomentService) -> None:
    if not await _caller_allowed(message):
        return
    if happy_moment_service.active_moment is not None and not _is_e2e_happy_active(
        happy_moment_service
    ):
        await message.answer("E2E_HOOK_REFUSED happy_end non-E2E Happy Moment is active")
        return
    await happy_moment_service.end_moment()
    await message.answer("E2E_HOOK_OK happy_end ended_or_not_active")


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
        active_state = heist_service.get_heist_state(chat_id)
        if not _is_e2e_heist_state(active_state):
            await message.answer(
                "E2E_HOOK_REFUSED heist_start non-E2E Heist is active in this chat"
            )
            return
        # Restart only our own synthetic state. Do not call real end_heist here:
        # it can pay out, so replacing an active event must never mutate economy.
        heist_service.active_heists.pop(chat_id, None)

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
    state.e2e_owned = True
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
                "source": E2E_SOURCE,
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
    await message.answer("E2E_HOOK_OK heist_start started_for_this_chat")


@router.message(Command("e2e_heist_end"), flags=flags)
async def cmd_e2e_heist_end(message: Message, heist_service: HeistService) -> None:
    if not await _caller_allowed(message):
        return
    state = heist_service.get_heist_state(message.chat.id)
    if state is not None and not _is_e2e_heist_state(state):
        await message.answer("E2E_HOOK_REFUSED heist_end non-E2E Heist is active in this chat")
        return
    await heist_service.end_heist(message.chat.id)
    await message.answer("E2E_HOOK_OK heist_end ended_or_not_active")
