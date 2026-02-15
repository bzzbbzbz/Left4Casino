# [START SPEC:TASK-010:transfer-handler]
import uuid

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.repositories import RepositoryFactory

router = Router()


@router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject, repo_factory: RepositoryFactory):
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

    user_repo = repo_factory.create_user_repo()
    event_repo = repo_factory.create_event_repo()

    if message.reply_to_message:
        to_user_id = message.reply_to_message.from_user.id
        to_user_name = message.reply_to_message.from_user.full_name
    elif target_username:
        if target_username.startswith("@"):
            user = await user_repo.get_user_by_nickname(target_username)
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

    sender_balance = await user_repo.get_balance(from_user_id, 0)
    if sender_balance < amount:
        await message.answer("❌ Недостаточно средств или ошибка транзакции.")
        return

    success = await user_repo.transfer(from_user_id, to_user_id, amount)
    if not success:
        await message.answer("❌ Недостаточно средств или ошибка транзакции.")
        return

    event_id_out = str(uuid.uuid4())
    event_id_in = str(uuid.uuid4())
    chat_id = message.chat.id

    await event_repo.add_event(event_id_out, from_user_id, "transfer_out", -amount, None, chat_id)
    await event_repo.add_event(event_id_in, to_user_id, "transfer_in", amount, None, chat_id)

    new_balance = sender_balance - amount
    if new_balance <= 0:
        await event_repo.add_event(str(uuid.uuid4()), from_user_id, "bankruptcy", 0, None, chat_id)
        await user_repo.increment_bankruptcy_count(from_user_id)

    await message.answer(f"✅ Успешно передано {amount} монет пользователю {to_user_name}!")


# [END SPEC:TASK-010:transfer-handler]
