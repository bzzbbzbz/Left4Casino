from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.db import Database
from bot.utils.formatters import format_number

router = Router()


@router.message(Command("safe"))
async def cmd_safe(message: Message, command: CommandObject, db: Database):
    """
    Safe (protected account) command.
    /safe           - show safe balance
    /safe 50        - deposit 50 to safe
    /safe -50       - withdraw 50 from safe
    """
    # Only works in group chats
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в групповых чатах.")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Get current balances
    balance = await db.get_balance(user_id)
    safe_balance = await db.get_safe_balance(user_id)

    args = command.args

    # No arguments - show balance
    if not args:
        await message.answer(
            f"🔐 <b>В сейфе:</b> {format_number(safe_balance)} очков\n"
            f"💰 <b>Баланс:</b> {format_number(balance)} очков"
        )
        return

    # Parse amount
    try:
        amount = int(args.strip())
    except ValueError:
        await message.answer("❌ Укажите сумму: /safe 50 (положить) или /safe -50 (снять)")
        return

    if amount == 0:
        await message.answer("❌ Укажите сумму: /safe 50 (положить) или /safe -50 (снять)")
        return

    # Deposit (positive amount)
    if amount > 0:
        if amount < 1:
            await message.answer("❌ Минимальная сумма: 1 очко")
            return

        # Check for active duel
        active_challenge = await db.get_active_challenge_by_user(user_id, chat_id)
        if active_challenge:
            await message.answer("❌ Нельзя класть в сейф во время активной дуэли или вызова.")
            return

        if balance < amount:
            await message.answer(
                f"❌ Недостаточно средств на балансе.\n\n"
                f"💰 Баланс: {format_number(balance)} очков\n"
                f"🔐 В сейфе: {format_number(safe_balance)} очков\n\n"
                f"Максимум можно положить: {format_number(balance)}"
            )
            return

        result = await db.safe_deposit(user_id, amount, chat_id)

        if result[0]:
            new_balance, new_safe_balance = result[1], result[2]
            await message.answer(
                f"✅ Положено в сейф: {format_number(amount)} очков\n\n"
                f"🔐 В сейфе: {format_number(new_safe_balance)} очков\n"
                f"💰 Баланс: {format_number(new_balance)} очков"
            )
        else:
            await message.answer(f"❌ Ошибка: {result[1]}")

    # Withdraw (negative amount)
    else:
        withdraw_amount = abs(amount)

        if withdraw_amount < 1:
            await message.answer("❌ Минимальная сумма: 1 очко")
            return

        if safe_balance < withdraw_amount:
            await message.answer(
                f"❌ Недостаточно средств в сейфе.\n\n"
                f"🔐 В сейфе: {format_number(safe_balance)} очков\n"
                f"💰 Баланс: {format_number(balance)} очков\n\n"
                f"Максимум можно снять: {format_number(safe_balance)}"
            )
            return

        result = await db.safe_withdraw(user_id, withdraw_amount, chat_id)

        if result[0]:
            new_balance, new_safe_balance = result[1], result[2]
            await message.answer(
                f"✅ Снято из сейфа: {format_number(withdraw_amount)} очков\n\n"
                f"🔐 В сейфе: {format_number(new_safe_balance)} очков\n"
                f"💰 Баланс: {format_number(new_balance)} очков"
            )
        else:
            await message.answer(f"❌ Ошибка: {result[1]}")
