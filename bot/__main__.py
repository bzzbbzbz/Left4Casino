import asyncio

import pytz
import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from structlog.typing import FilteringBoundLogger

from bot.config_reader import (
    AIConfig,
    BotConfig,
    ChatRestrictionsConfig,
    FSMMode,
    GameConfig,
    LogConfig,
    RedisConfig,
    ReportsConfig,
    get_config,
)
from bot.db import Database
from bot.fluent_loader import get_fluent_localization
from bot.handlers import ai_credit, default_commands, group_games, spin, transfer
from bot.logs import get_structlog_config
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.restrictions import ChatRestrictionMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.tracker import GroupTrackerMiddleware
from bot.services.ai import AIClient
from bot.services.backfill import backfill_usernames
from bot.services.daily_stats import DailyStatsService
from bot.ui_commands import set_bot_commands


async def main():
    log_config = get_config(model=LogConfig, root_key="logs")
    structlog.configure(**get_structlog_config(log_config))

    db = Database()
    await db.create_tables()

    # Terminate any active AI sessions from previous run
    await db.terminate_all_active_sessions()

    # --- MIGRATION START ---
    # Uncomment to run stats backfill once, then comment out or remove
    # await db.run_stats_backfill()
    await db.run_bankruptcy_backfill()
    # --- MIGRATION END ---

    bot_config = get_config(model=BotConfig, root_key="bot")
    bot = Bot(
        token=bot_config.token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    if bot_config.fsm_mode == FSMMode.REDIS:
        redis_config = get_config(model=RedisConfig, root_key="redis")
        storage = RedisStorage.from_url(
            url=str(redis_config.dsn),
            connection_kwargs={"decode_responses": True},
        )
    else:
        storage = MemoryStorage()

    # Loading localization for bot
    l10n = get_fluent_localization()

    game_config = get_config(model=GameConfig, root_key="game_config")
    chat_restrictions_config = get_config(
        model=ChatRestrictionsConfig, root_key="chat_restrictions"
    )
    ai_config = get_config(model=AIConfig, root_key="ai")
    reports_config = get_config(model=ReportsConfig, root_key="reports")

    ai_client = AIClient(ai_config)

    # Creating dispatcher with some dependencies
    dp = Dispatcher(
        storage=storage,
        l10n=l10n,
        game_config=game_config,
        db=db,
        ai_client=ai_client,
        ai_config=ai_config,
    )

    # Register middleware
    dp.update.outer_middleware(LoggingMiddleware())
    dp.message.outer_middleware(GroupTrackerMiddleware())
    dp.message.middleware(ChatRestrictionMiddleware(chat_restrictions_config))

    # Make bot work only in PM (one-on-one chats) with bot
    # dp.message.filter(F.chat.type == "private")

    # Register routers with handlers
    dp.include_router(default_commands.router)
    dp.include_router(spin.router)
    dp.include_router(group_games.router)
    dp.include_router(transfer.router)
    dp.include_router(ai_credit.router)

    # Register throttling middleware
    dp.message.middleware(
        ThrottlingMiddleware(game_config.throttle_time_spin, game_config.throttle_time_other)
    )

    # Set bot commands in the UI
    await set_bot_commands(bot, l10n)

    # Start username backfill in background
    asyncio.create_task(backfill_usernames(bot, db))

    # Setup Scheduler
    scheduler = AsyncIOScheduler()
    daily_stats_service = DailyStatsService(db, bot)
    timezone = pytz.timezone(reports_config.timezone)

    async def send_daily_reports():
        # Send to all allowed chats
        for chat_id in chat_restrictions_config.allowed_chat_ids:
            try:
                # Convert string chat_id to int if necessary
                cid = int(chat_id)
                await daily_stats_service.generate_and_send_report(cid)
            except Exception:
                pass

    async def send_draft_report():
        # Send draft to specific user
        target_user_id = reports_config.admin_id
        if target_user_id == 0:
            return
        # Use today's stats for the draft sent at 23:30
        await daily_stats_service.generate_and_send_report(
            target_user_id, is_dry_run=True, use_today=True
        )

    # Schedule daily report at 00:00 UTC+5
    scheduler.add_job(send_daily_reports, "cron", hour=0, minute=0, timezone=timezone)

    # Schedule draft report at 23:30 UTC+5
    scheduler.add_job(send_draft_report, "cron", hour=20, minute=19, timezone=timezone)

    scheduler.start()

    logger: FilteringBoundLogger = structlog.get_logger()
    await logger.ainfo("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
