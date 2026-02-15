import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.utils.context import db_actions_ctx

logger = structlog.get_logger()


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start_time = time.time()

        # Extract user info
        user = data.get("event_from_user")
        nickname = (
            f"@{user.username}"
            if user and user.username
            else (user.first_name if user else "Unknown")
        )
        user_id = user.id if user else None

        # Determine action
        action = "Unknown"
        if isinstance(event, Message):
            if event.text:
                action = f"Message: {event.text[:50]}"
            elif event.caption:
                action = f"Caption: {event.caption[:50]}"
            elif event.dice:
                action = f"Dice: {event.dice.emoji} ({event.dice.value})"
            elif event.content_type:
                action = f"Message ({event.content_type})"
        elif isinstance(event, CallbackQuery):
            action = f"Callback: {event.data}"

        # Initialize DB action tracking
        token = db_actions_ctx.set([])

        error = None
        try:
            result = await handler(event, data)
            return result
        except Exception as e:
            error = str(e)
            raise e
        finally:
            duration = int((time.time() - start_time) * 1000)
            db_actions = db_actions_ctx.get()
            db_actions_ctx.reset(token)

            log_event = {
                "event": "Update handled",
                "update_id": event.update_id if hasattr(event, "update_id") else None,
                "duration_ms": duration,
                "user_id": user_id,
                "nickname": nickname,
                "action": action,
                "db_actions": db_actions,
                "error": error,
            }

            # We use 'info' even for errors here to keep the main log stream consistent,
            # but if error is present, maybe 'error' level is better?
            # The user just asked to see it in the line.
            if error:
                logger.error(**log_event)
            else:
                logger.info(**log_event)
