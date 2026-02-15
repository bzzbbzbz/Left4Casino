from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.db import Database
from bot.services.group_tracker import save_group


class GroupTrackerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            chat = event.chat
            user = event.from_user

            if chat.type in ("group", "supergroup"):
                # Fire and forget saving (don't await if we don't want to block,
                # but for file I/O await is better to ensure consistency)
                await save_group(chat.id, chat.title or "Unknown Group")

                # Update user-group association
                db: Database = data.get("db")
                if db and user:
                    await db.update_user_group(user.id, chat.id)

        return await handler(event, data)
