"""Unit tests for Heist and Happy Moment runtime behavior."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.happy_moment import HappyMomentService, HappyMomentTier, ScheduledMoment
from bot.services.heist import HeistService, HeistState

pytestmark = pytest.mark.unit


def _heist_config() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        active_hours_start="08:00",
        active_hours_end="02:00",
        pot_cap_pct=5,
        min_pot_pct=1.0,
        seed_min_pct=1,
        seed_max_pct=1,
        commission_pct=10,
        base_value_noise_pct=0.0,
        base_value_fallback=1000,
        warning_before_minutes=10,
        phase1_min_minutes=10,
        phase1_max_minutes=10,
        phase2_min_minutes=2,
        phase2_max_minutes=2,
        seed_delay_minutes=5,
        max_duration_minutes=30,
        croupier_message_interval_seconds=120,
    )


@pytest.mark.asyncio
async def test_heist_check_seed_needed_applies_seed_and_logs_event() -> None:
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_db = MagicMock()
    mock_db.add_event = AsyncMock()
    service = HeistService(
        bot=mock_bot,
        db=mock_db,
        config=_heist_config(),
        allowed_chat_ids=[-1001],
    )

    now = datetime.now(service.timezone)
    service.active_heists[-1001] = HeistState(
        chat_id=-1001,
        base_value=1000,
        pot=0,
        pot_cap=50,
        seed_amount=15,
        phase="robbery",
        phase1_end=now + timedelta(minutes=10),
        phase2_end=None,
        phase2_duration=2,
        start_time=now,
    )

    await service.check_seed_needed(-1001)
    state = service.active_heists[-1001]
    assert state.pot == 15
    assert state.seed_applied is True
    mock_db.add_event.assert_awaited()
    mock_bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_heist_end_with_winner_pays_out_and_logs_commission() -> None:
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_db = MagicMock()
    mock_db.add_event = AsyncMock()
    mock_db.update_balance = AsyncMock()
    service = HeistService(
        bot=mock_bot,
        db=mock_db,
        config=_heist_config(),
        allowed_chat_ids=[-1002],
    )

    now = datetime.now(service.timezone)
    service.active_heists[-1002] = HeistState(
        chat_id=-1002,
        base_value=1000,
        pot=100,
        pot_cap=50,
        seed_amount=10,
        phase="alarm",
        phase1_end=now,
        phase2_end=now + timedelta(minutes=2),
        phase2_duration=2,
        last_spinner_id=777,
        last_spinner_first_name="Winner",
        start_time=now - timedelta(minutes=5),
    )

    await service.end_heist(-1002)

    mock_db.update_balance.assert_awaited_once_with(777, 90)
    event_types = [call.args[2] for call in mock_db.add_event.await_args_list]
    assert "heist_win" in event_types
    assert "heist_commission" in event_types
    assert -1002 not in service.active_heists


@pytest.mark.asyncio
async def test_happy_moment_start_sets_multiplier_and_notifies_chats() -> None:
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_db = MagicMock()
    mock_db.add_event = AsyncMock()
    service = HappyMomentService(
        bot=mock_bot,
        db=mock_db,
        allowed_chat_ids=[-10, -11],
        events_per_day=1,
        tiers=[HappyMomentTier(duration_minutes=1, multiplier=3.0)],
        enabled=True,
    )

    start_time = datetime.now(service.timezone) + timedelta(minutes=1)
    moment = ScheduledMoment(
        scheduled_time=start_time,
        tier=HappyMomentTier(duration_minutes=1, multiplier=3.0),
        name="Test Moment",
    )

    await service.start_moment(moment)

    assert service.is_active() is True
    assert service.get_active_multiplier() == 3.0
    mock_db.add_event.assert_awaited()
    assert mock_bot.send_message.await_count == 2


def test_happy_moment_expires_and_disables_multiplier() -> None:
    service = HappyMomentService(
        bot=MagicMock(),
        db=MagicMock(),
        allowed_chat_ids=[],
        events_per_day=1,
        tiers=[HappyMomentTier(duration_minutes=1, multiplier=2.0)],
        enabled=True,
    )

    now = datetime.now(service.timezone)
    service.active_moment = SimpleNamespace(
        start_time=now - timedelta(minutes=2),
        end_time=now - timedelta(minutes=1),
        tier=HappyMomentTier(duration_minutes=1, multiplier=2.0),
        name="Expired",
    )

    with patch("bot.services.happy_moment.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = now
        assert service.get_active_multiplier() is None
        assert service.is_active() is False
