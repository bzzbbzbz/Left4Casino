"""Unit tests for scheduler job registration in bot main."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import FSMMode

pytestmark = pytest.mark.unit


def _build_fake_dispatcher() -> MagicMock:
    dp = MagicMock()
    dp.update = MagicMock()
    dp.message = MagicMock()
    dp.callback_query = MagicMock()
    dp.start_polling = AsyncMock(return_value=None)
    return dp


@pytest.mark.asyncio
async def test_main_registers_duel_happy_heist_scheduler_jobs() -> None:
    with patch("dotenv.load_dotenv", return_value=True):
        from bot import __main__ as bot_main

    bot_token = MagicMock()
    bot_token.get_secret_value.return_value = "123:TEST"

    cfg_map = {
        "logs": SimpleNamespace(),
        "bot": SimpleNamespace(token=bot_token, fsm_mode=FSMMode.MEMORY),
        "game_config": SimpleNamespace(
            throttle_time_spin=2,
            throttle_time_other=1,
            throttle_time_top=5,
        ),
        "chat_restrictions": SimpleNamespace(allowed_chat_ids=[-100100], block_private_chats=False),
        "ai": SimpleNamespace(api_key="test-key", provider="mock", model="gpt-4o-mini"),
        "reports": SimpleNamespace(timezone="UTC", admin_id=1),
        "dice_fights": SimpleNamespace(challenge_timeout_minutes=5, roll_timeout_minutes=5),
        "happy_moment": SimpleNamespace(
            enabled=True,
            events_per_day=1,
            active_hours_weight=100,
            active_hours_start="08:00",
            active_hours_end="22:00",
            tiers=[SimpleNamespace(duration_minutes=1, multiplier=2.0)],
        ),
        "heist": SimpleNamespace(
            enabled=True,
            warning_before_minutes=10,
            seed_delay_minutes=5,
            croupier_message_interval_seconds=60,
            max_duration_minutes=30,
        ),
    }

    def _fake_get_config(model, root_key, required=True):  # noqa: ARG001
        return cfg_map[root_key]

    scheduler_mock = MagicMock()
    scheduler_mock.add_job = MagicMock()
    scheduler_mock.start = MagicMock()

    bot_mock = MagicMock()
    bot_mock.session = MagicMock()
    bot_mock.session.close = AsyncMock()
    bot_mock.edit_message_text = AsyncMock()

    db_mock = MagicMock()
    db_mock.db_path = "/tmp/test-main.db"
    db_mock.create_tables = AsyncMock()
    db_mock.terminate_all_active_sessions = AsyncMock()
    db_mock.run_bankruptcy_backfill = AsyncMock()

    happy_service = MagicMock()
    future_moment = SimpleNamespace(
        scheduled_time=datetime.now(UTC) + timedelta(minutes=5),
        tier=SimpleNamespace(duration_minutes=1),
    )
    happy_service.generate_daily_schedule.return_value = [future_moment]
    happy_service.start_moment = AsyncMock()
    happy_service.end_moment = AsyncMock()

    heist_service = MagicMock()
    heist_service.generate_daily_schedule.return_value = datetime.now(UTC) + timedelta(minutes=30)
    heist_service.start_heist = AsyncMock()
    heist_service.send_warning = AsyncMock()
    heist_service.check_seed_needed = AsyncMock()
    heist_service.check_phase1_end = AsyncMock()
    heist_service.end_heist = AsyncMock()
    heist_service.send_croupier_message = AsyncMock()
    heist_service.get_heist_state.return_value = None
    heist_service.active_heists = {}

    logger_mock = MagicMock()
    logger_mock.ainfo = AsyncMock(return_value=None)

    with patch.object(bot_main, "get_config", side_effect=_fake_get_config):
        with patch.object(bot_main, "Database", return_value=db_mock):
            with patch.object(bot_main, "Bot", return_value=bot_mock):
                with patch.object(bot_main, "Dispatcher", return_value=_build_fake_dispatcher()):
                    with patch.object(bot_main, "AsyncIOScheduler", return_value=scheduler_mock):
                        with patch.object(
                            bot_main, "HappyMomentService", return_value=happy_service
                        ):
                            with patch.object(bot_main, "HeistService", return_value=heist_service):
                                with patch.object(
                                    bot_main, "get_structlog_config", return_value={}
                                ):
                                    with patch.object(bot_main, "set_bot_commands", AsyncMock()):
                                        with patch.object(
                                            bot_main, "backfill_usernames", MagicMock()
                                        ):
                                            with patch.object(
                                                bot_main.asyncio, "create_task", MagicMock()
                                            ):
                                                with patch.object(
                                                    bot_main.structlog,
                                                    "get_logger",
                                                    return_value=logger_mock,
                                                ):
                                                    await bot_main.main()

    job_names = []
    for call in scheduler_mock.add_job.call_args_list:
        fn = call.args[0]
        job_names.append(getattr(fn, "__name__", str(fn)))

    assert "check_expired_challenges" in job_names
    assert "check_duel_timeouts" in job_names
    assert "generate_happy_moment_schedule" in job_names
    assert "generate_heist_schedule" in job_names
    assert "start_happy_moment" in job_names
    assert "start_heist" in job_names
    assert scheduler_mock.start.called
