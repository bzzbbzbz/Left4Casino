import asyncio
from datetime import datetime, timedelta

import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from structlog.typing import FilteringBoundLogger

from bot.config_reader import LogConfig, get_config, BotConfig, FSMMode, RedisConfig, GameConfig, ChatRestrictionsConfig, AIConfig, ReportsConfig, DiceFightsConfig, HappyMomentConfig, HeistConfig
from bot.db import Database
from bot.fluent_loader import get_fluent_localization
from bot.handlers import default_commands, group_games, transfer, ai_credit, dice_fight, safe
from bot.logs import get_structlog_config
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.restrictions import ChatRestrictionMiddleware
from bot.middlewares.tracker import GroupTrackerMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.services.ai import AIClient
from bot.services.backfill import backfill_usernames
from bot.services.daily_stats import DailyStatsService
from bot.services.happy_moment import HappyMomentService, HappyMomentTier, ScheduledMoment
from bot.services.heist import HeistService
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
    #await db.run_stats_backfill()
    await db.run_bankruptcy_backfill()
    # --- MIGRATION END ---

    bot_config = get_config(model=BotConfig, root_key="bot")
    bot = Bot(
        token=bot_config.token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
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
    chat_restrictions_config = get_config(model=ChatRestrictionsConfig, root_key="chat_restrictions")
    ai_config = get_config(model=AIConfig, root_key="ai")
    reports_config = get_config(model=ReportsConfig, root_key="reports")
    
    dice_fights_config = get_config(
        model=DiceFightsConfig, root_key="dice_fights", required=False
    )
    happy_moment_config = get_config(
        model=HappyMomentConfig, root_key="happy_moment", required=False
    )
    heist_config = get_config(
        model=HeistConfig, root_key="heist", required=False
    )
    
    ai_client = AIClient(ai_config)
    
    # Convert config tiers to service tiers
    happy_moment_tiers = [
        HappyMomentTier(duration_minutes=t.duration_minutes, multiplier=t.multiplier)
        for t in happy_moment_config.tiers
    ]
    
    # Happy moment service will be initialized after bot is created
    happy_moment_service = HappyMomentService(
        bot=bot,
        db=db,
        allowed_chat_ids=chat_restrictions_config.allowed_chat_ids,
        timezone_str=reports_config.timezone,
        events_per_day=happy_moment_config.events_per_day,
        active_hours_weight=happy_moment_config.active_hours_weight,
        active_hours_start=happy_moment_config.active_hours_start,
        active_hours_end=happy_moment_config.active_hours_end,
        tiers=happy_moment_tiers,
        enabled=happy_moment_config.enabled,
    )
    
    # Heist service
    heist_service = HeistService(
        bot=bot,
        db=db,
        config=heist_config,
        allowed_chat_ids=chat_restrictions_config.allowed_chat_ids,
        timezone_str=reports_config.timezone,
    )

    # Creating dispatcher with some dependencies
    dp = Dispatcher(
        storage=storage,
        l10n=l10n,
        game_config=game_config,
        db=db,
        ai_client=ai_client,
        ai_config=ai_config,
        dice_fights_config=dice_fights_config,
        happy_moment_service=happy_moment_service,
        heist_service=heist_service,
        bot=bot
    )
    
    # Register middleware
    dp.update.outer_middleware(LoggingMiddleware())
    dp.message.outer_middleware(GroupTrackerMiddleware())
    dp.message.middleware(ChatRestrictionMiddleware(chat_restrictions_config))
    dp.callback_query.middleware(ChatRestrictionMiddleware(chat_restrictions_config))

    # Make bot work only in PM (one-on-one chats) with bot
    # dp.message.filter(F.chat.type == "private")

    # Register routers with handlers
    dp.include_router(default_commands.router)
    dp.include_router(group_games.router)
    dp.include_router(transfer.router)
    dp.include_router(ai_credit.router)
    dp.include_router(dice_fight.router)
    dp.include_router(safe.router)

    # Register throttling middleware
    dp.message.middleware(
        ThrottlingMiddleware(game_config.throttle_time_spin, game_config.throttle_time_other, game_config.throttle_time_top)
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
        await daily_stats_service.generate_and_send_report(target_user_id, is_dry_run=True, use_today=True)

    # Schedule daily report at 00:00 UTC+5
    scheduler.add_job(send_daily_reports, 'cron', hour=0, minute=0, timezone=timezone)
    
    # Schedule draft report at 23:30 UTC+5
    scheduler.add_job(send_draft_report, 'cron', hour=20, minute=19, timezone=timezone)
    
    # Dice fights timeout handlers
    async def check_expired_challenges():
        """Expire pending challenges older than timeout"""
        expired = await db.get_expired_challenges_with_message(dice_fights_config.challenge_timeout_minutes)
        for challenge in expired:
            try:
                await db.cancel_challenge(challenge['challenge_id'])
                # Edit the message to show expiration
                if challenge.get('message_id'):
                    from contextlib import suppress
                    from aiogram.exceptions import TelegramBadRequest
                    import html
                    nickname = challenge.get('initiator_nickname') or "Игрок"
                    bet = challenge.get('bet_amount', 0)
                    with suppress(TelegramBadRequest):
                        await bot.edit_message_text(
                            chat_id=challenge['chat_id'],
                            message_id=challenge['message_id'],
                            text=f"⏰ <b>Вызов истёк</b>\n\nНикто не принял вызов @{html.escape(str(nickname))} на {bet} очков."
                        )
            except Exception:
                pass
    
    async def check_duel_timeouts():
        """Auto-roll for players who didn't roll in time"""
        timed_out = await db.get_timed_out_duels(dice_fights_config.roll_timeout_minutes)
        for challenge in timed_out:
            try:
                await dice_fight.auto_roll_for_timeout(db, bot, challenge)
            except Exception:
                pass
    
    scheduler.add_job(check_expired_challenges, 'interval', minutes=1)
    scheduler.add_job(check_duel_timeouts, 'interval', seconds=30)
    
    # Happy moment scheduler jobs
    async def generate_happy_moment_schedule():
        """Generate daily schedule for happy moments (called at 00:00)"""
        moments = happy_moment_service.generate_daily_schedule()
        
        # Schedule each moment
        for moment in moments:
            scheduler.add_job(
                start_happy_moment,
                'date',
                run_date=moment.scheduled_time,
                args=[moment],
                id=f"happy_moment_{moment.scheduled_time.isoformat()}",
                replace_existing=True,
            )
    
    async def start_happy_moment(moment):
        """Start a happy moment and schedule its end"""
        await happy_moment_service.start_moment(moment)

        # Schedule end
        end_time = moment.scheduled_time + timedelta(minutes=moment.tier.duration_minutes)
        scheduler.add_job(
            end_happy_moment,
            'date',
            run_date=end_time,
            id=f"happy_moment_end_{moment.scheduled_time.isoformat()}",
            replace_existing=True,
        )
    
    async def end_happy_moment():
        """End the current happy moment"""
        await happy_moment_service.end_moment()
    
    # Schedule daily generation at 00:00
    scheduler.add_job(generate_happy_moment_schedule, 'cron', hour=0, minute=0, timezone=timezone)
    
    # Generate initial schedule on startup
    if happy_moment_config.enabled:
        moments = happy_moment_service.generate_daily_schedule()
        for moment in moments:
            scheduler.add_job(
                start_happy_moment,
                'date',
                run_date=moment.scheduled_time,
                args=[moment],
                id=f"happy_moment_{moment.scheduled_time.isoformat()}",
                replace_existing=True,
            )
    
    # Heist scheduler jobs
    async def generate_heist_schedule():
        """Generate daily schedule for heist (called at 00:00)"""
        scheduled_time = heist_service.generate_daily_schedule()
        
        if scheduled_time:
            # Schedule warning (10 minutes before)
            warning_time = scheduled_time - timedelta(minutes=heist_config.warning_before_minutes)
            scheduler.add_job(
                send_heist_warning,
                'date',
                run_date=warning_time,
                id=f"heist_warning_{scheduled_time.date().isoformat()}",
                replace_existing=True,
            )
            
            # Schedule start
            scheduler.add_job(
                start_heist,
                'date',
                run_date=scheduled_time,
                id=f"heist_start_{scheduled_time.date().isoformat()}",
                replace_existing=True,
            )
    
    async def send_heist_warning():
        """Send heist warning to all chats"""
        await heist_service.send_warning()
    
    async def start_heist():
        """Start heist event"""
        await heist_service.start_heist()

        # Schedule seed check (5 minutes after start)
        seed_time = datetime.now(timezone) + timedelta(minutes=heist_config.seed_delay_minutes)
        scheduler.add_job(
            check_heist_seed,
            'date',
            run_date=seed_time,
            id=f"heist_seed_{datetime.now(timezone).isoformat()}",
            replace_existing=True,
        )
        
        # Schedule phase 1 checks (every minute)
        scheduler.add_job(
            check_phase1_ends,
            'interval',
            minutes=1,
            id="heist_phase1_check",
            replace_existing=True,
        )
        
        # Schedule croupier messages (every 2 minutes)
        scheduler.add_job(
            send_heist_croupier_messages,
            'interval',
            seconds=heist_config.croupier_message_interval_seconds,
            id="heist_croupier_messages",
            replace_existing=True,
        )
        
        # Schedule hard cap (30 minutes max)
        hard_cap_time = datetime.now(timezone) + timedelta(minutes=heist_config.max_duration_minutes)
        scheduler.add_job(
            end_all_heists,
            'date',
            run_date=hard_cap_time,
            id=f"heist_hard_cap_{datetime.now(timezone).isoformat()}",
            replace_existing=True,
        )
    
    async def check_heist_seed():
        """Check if seed is needed for all active heists"""
        for chat_id in heist_service.active_heists.keys():
            await heist_service.check_seed_needed(chat_id)
    
    async def check_phase1_ends():
        """Check if phase 1 should end for any active heist"""
        for chat_id in list(heist_service.active_heists.keys()):
            await heist_service.check_phase1_end(chat_id)
            
            # Check if phase 2 should end
            state = heist_service.get_heist_state(chat_id)
            if state and state.phase == 'alarm' and state.phase2_end:
                now = datetime.now(timezone)
                if now >= state.phase2_end:
                    await heist_service.end_heist(chat_id)
    
    async def send_heist_croupier_messages():
        """Send periodic croupier messages to all active heists"""
        for chat_id in list(heist_service.active_heists.keys()):
            await heist_service.send_croupier_message(chat_id)
    
    async def end_all_heists():
        """End all active heists (hard cap)"""
        for chat_id in list(heist_service.active_heists.keys()):
            await heist_service.end_heist(chat_id)
        
        # Remove periodic jobs
        try:
            scheduler.remove_job("heist_phase1_check")
            scheduler.remove_job("heist_croupier_messages")
        except Exception:
            pass
    
    # Schedule daily generation at 00:00
    scheduler.add_job(generate_heist_schedule, 'cron', hour=0, minute=0, timezone=timezone)
    
    # Generate initial schedule on startup
    if heist_config.enabled:
        scheduled_time = heist_service.generate_daily_schedule()
        if scheduled_time:
            # Schedule warning
            warning_time = scheduled_time - timedelta(minutes=heist_config.warning_before_minutes)
            now = datetime.now(timezone)
            
            if warning_time > now:
                scheduler.add_job(
                    send_heist_warning,
                    'date',
                    run_date=warning_time,
                    id=f"heist_warning_{scheduled_time.date().isoformat()}",
                    replace_existing=True,
                )
            
            if scheduled_time > now:
                scheduler.add_job(
                    start_heist,
                    'date',
                    run_date=scheduled_time,
                    id=f"heist_start_{scheduled_time.date().isoformat()}",
                    replace_existing=True,
                )
    
    scheduler.start()

    logger: FilteringBoundLogger = structlog.get_logger()
    await logger.ainfo("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
