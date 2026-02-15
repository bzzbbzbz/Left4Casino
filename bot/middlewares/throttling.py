from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message
from cachetools import TTLCache


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(
        self,
        throttle_time_spin: int,
        throttle_time_other: int,
        throttle_time_top: int = 5,
    ):
        self.caches = {
            "spin": TTLCache(maxsize=10_000, ttl=throttle_time_spin),
            "default": TTLCache(maxsize=10_000, ttl=throttle_time_other),
            "top": TTLCache(maxsize=10_000, ttl=throttle_time_top),
        }

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        throttling_key = get_flag(data, "throttling_key")
        if throttling_key is not None and throttling_key in self.caches:
            if event.chat.id in self.caches[throttling_key]:
                return
            else:
                self.caches[throttling_key][event.chat.id] = None
        return await handler(event, data)
