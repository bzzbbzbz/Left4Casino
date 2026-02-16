import asyncio

import aiosqlite
import structlog
from aiogram import Bot

from bot.db import Database

logger = structlog.get_logger()


async def backfill_usernames(bot: Bot, db: Database):
    """
    Background task to fetch and update usernames for all users in the database.
    This ensures that even users who haven't interacted with the bot recently
    have their usernames updated for commands like /give.
    """
    await logger.ainfo("Starting username backfill process...")

    users_to_update = []

    try:
        # Read directly from DB to get all users
        async with aiosqlite.connect(db.db_path) as db_conn:
            async with db_conn.execute("SELECT user_id, nickname FROM users") as cursor:
                async for row in cursor:
                    users_to_update.append({"user_id": row[0], "current_nickname": row[1]})

        await logger.ainfo(f"Found {len(users_to_update)} users to check.")

        updated_count = 0
        errors_count = 0

        for user in users_to_update:
            user_id = user["user_id"]
            current_nickname = user["current_nickname"]

            try:
                # Get chat info from Telegram
                chat = await bot.get_chat(user_id)
                username = chat.username

                if username:
                    if username != current_nickname:
                        await db.register_user(user_id, username)
                        await logger.adebug(
                            f"Updated user {user_id}: {current_nickname} -> {username}"
                        )
                        updated_count += 1

            except Exception as e:
                await logger.aerror(f"Error updating user {user_id}: {e}")
                errors_count += 1

            # Sleep to respect rate limits
            await asyncio.sleep(0.2)

        await logger.ainfo(
            f"Username backfill completed. Updated: {updated_count}, Errors: {errors_count}"
        )

    except Exception as e:
        await logger.aerror(f"Critical error in username backfill: {e}")
