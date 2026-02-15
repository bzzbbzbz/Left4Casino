from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config_reader import ChatRestrictionsConfig


class ChatRestrictionMiddleware(BaseMiddleware):
    def __init__(self, config: ChatRestrictionsConfig):
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        chat_id = event.chat.id
        chat_type = event.chat.type

        # Block private chats if configured
        if self.config.block_private_chats and chat_type == "private":
            return

        # Whitelist
        if self.config.allowed_chat_ids:
            if chat_id not in self.config.allowed_chat_ids:
                return

        return await handler(event, data)
