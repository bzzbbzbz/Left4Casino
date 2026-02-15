from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from fluent.runtime import FluentLocalization

from bot.config_reader import GameConfig
from bot.db import Database
from bot.keyboards import get_spin_keyboard

flags = {"throttling_key": "default"}
router = Router()


@router.message(Command("start"), flags=flags)
async def cmd_start(
    message: Message,
    state: FSMContext,
    l10n: FluentLocalization,
    game_config: GameConfig,
    db: Database,
):
    # Register user in DB to ensure they can be found by nickname
    if message.from_user.username:
        await db.register_user(message.from_user.id, message.from_user.username)

    # Get actual balance from DB (or initialize if new)
    balance = await db.get_balance(message.from_user.id, game_config.starting_points)

    # Sync FSM state with DB balance (optional, if we transition fully to DB)
    # But for now, let's keep FSM updated just in case
    await state.update_data(score=balance)

    start_text = l10n.format_value("start-text", {"points": balance})

    await message.answer(start_text, reply_markup=get_spin_keyboard(l10n))


@router.message(Command("stop"), flags=flags)
async def cmd_stop(message: Message, l10n: FluentLocalization):
    await message.answer(l10n.format_value("stop-text"), reply_markup=ReplyKeyboardRemove())


@router.message(Command("help"), flags=flags)
async def cmd_help(message: Message, l10n: FluentLocalization):
    await message.answer(l10n.format_value("help-text"), disable_web_page_preview=True)


@router.message(Command("bid"), flags=flags)
async def cmd_bid(message: Message, command: CommandObject, db: Database, game_config: GameConfig):
    user_id = message.from_user.id
    if not command.args:
        current_bid = await db.get_bid(user_id)
        await message.reply(f"Ваша текущая ставка: {current_bid}")
        return

    try:
        bid_amount = int(command.args)
        if bid_amount <= 0:
            await message.reply("Ставка должна быть положительным числом.")
            return

        current_balance = await db.get_balance(user_id, game_config.starting_points)
        if bid_amount > current_balance:
            # Если ставка больше баланса, идем ва-банк
            await db.update_bid(user_id, current_balance)
            await message.reply(
                f"Недостаточно средств для ставки {bid_amount}. Вы пошли ва-банк! Ставка установлена в размере: {current_balance}"
            )
            return

        await db.update_bid(user_id, bid_amount)
        await message.reply(f"Ваша ставка обновлена: {bid_amount}")
    except ValueError:
        await message.reply("Пожалуйста, укажите целое число.")
