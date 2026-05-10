from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)
from fluent.runtime import FluentLocalization


async def set_bot_commands(bot: Bot, l10n: FluentLocalization):
    commands = [
        BotCommand(command="balance", description=l10n.format_value("menu-balance")),
        BotCommand(command="bid", description=l10n.format_value("menu-bid")),
        BotCommand(command="safe", description=l10n.format_value("menu-safe")),
        BotCommand(command="stats", description=l10n.format_value("menu-stats")),
        BotCommand(command="top", description=l10n.format_value("menu-top")),
        BotCommand(command="dice", description=l10n.format_value("menu-dice")),
        BotCommand(command="take", description=l10n.format_value("menu-take")),
        BotCommand(command="give", description=l10n.format_value("menu-give")),
        BotCommand(command="credit", description=l10n.format_value("menu-credit")),
        BotCommand(command="help", description=l10n.format_value("menu-help")),
    ]
    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeAllGroupChats())
