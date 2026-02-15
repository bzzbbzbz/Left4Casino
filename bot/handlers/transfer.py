import uuid

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.db import Database

router = Router()


@router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject, db: Database):
    args = command.args
    if not args:
        await message.answer("Использование: /give <сумма> <@username> или ответом на сообщение")
        return

    parts = args.split()
    amount_str = parts[0]
    target_username = parts[1] if len(parts) > 1 else None

    if not amount_str.isdigit():
        await message.answer("Сумма должна быть числом.")
        return

    amount = int(amount_str)
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return

    from_user_id = message.from_user.id
    to_user_id = None
    to_user_name = None

    # Determine recipient
    if message.reply_to_message:
        to_user_id = message.reply_to_message.from_user.id
        to_user_name = message.reply_to_message.from_user.full_name
    elif target_username:
        if target_username.startswith("@"):
            user = await db.get_user_by_nickname(target_username)
            if user:
                to_user_id = user["user_id"]
                to_user_name = user["nickname"] or "Unknown"
            else:
                await message.answer("Пользователь не найден.")
                return
        else:
            await message.answer("Укажите @username пользователя.")
            return
    else:
        await message.answer("Укажите получателя.")
        return

    if from_user_id == to_user_id:
        await message.answer("Нельзя передать монеты самому себе.")
        return

    # Execute transfer
    event_id_out = str(uuid.uuid4())
    event_id_in = str(uuid.uuid4())

    success = await db.transfer_money(
        from_user_id, to_user_id, amount, event_id_out, event_id_in, chat_id=message.chat.id
    )

    if success:
        await message.answer(f"✅ Успешно передано {amount} монет пользователю {to_user_name}!")
        # Optionally notify recipient? They might not be in context if using username.
    else:
        await message.answer("❌ Недостаточно средств или ошибка транзакции.")
