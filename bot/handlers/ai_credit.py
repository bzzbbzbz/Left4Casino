import uuid
from datetime import datetime, timedelta

import structlog
from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import Message

from bot.config_reader import AIConfig
from bot.db import Database
from bot.services.ai import AIClient

router = Router()
logger = structlog.get_logger()


class InDialogueFilter(Filter):
    async def __call__(self, message: Message, db: Database) -> bool:
        user = await db.get_user(message.from_user.id)
        return user is not None and user["state"] == "IN_DIALOGUE"


@router.message(Command("credit"))
async def cmd_credit(message: Message, db: Database, ai_client: AIClient, ai_config: AIConfig):
    user_id = message.from_user.id
    # Check balance
    balance = await db.get_balance(user_id)
    if balance > 0:
        await message.reply("У тебя еще есть фишки! Возвращайся, когда все проиграешь.")
        return

    # Check active session
    active_session = await db.get_active_session(user_id)
    if active_session:
        await message.reply("У нас уже идет диалог. Ответь мне!")
        return

    # Check last credit time
    last_credit = await db.get_last_credit_event(user_id)
    if last_credit:
        last_time_str = last_credit["created_at"]
        # Parse time. SQLite usually returns YYYY-MM-DD HH:MM:SS
        try:
            last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
            cooldown_duration = timedelta(minutes=ai_config.credit_cooldown_minutes)
            if datetime.now() - last_time < cooldown_duration:
                remaining = cooldown_duration - (datetime.now() - last_time)
                minutes = int(remaining.total_seconds() // 60) + 1
                await message.reply(
                    f"Банк закрыт на перерыв. Приходите через {minutes} мин.\nПопробуйте попросить фишки у других игроков в чате!"
                )
                return
        except ValueError:
            # If parsing fails, we ignore the restriction to be safe, or log error
            pass

    # Start session
    session_id = str(uuid.uuid4())
    await db.create_credit_session(session_id, user_id)
    await db.update_user_state(user_id, "IN_DIALOGUE")

    # Initial AI message
    try:
        greeting = await ai_client.generate_initial_greeting()
        await db.add_dialogue_message(session_id, "assistant", greeting)
        await message.reply(greeting)
    except Exception as e:
        await logger.aerror("AI Error during greeting", error=str(e))
        await db.update_user_state(user_id, "IDLE")
        await message.reply("Банкир сейчас на обеде. Попробуй зайти позже.")


@router.message(F.text, InDialogueFilter())
async def process_dialogue(message: Message, db: Database, ai_client: AIClient):
    user_id = message.from_user.id
    active_session = await db.get_active_session(user_id)

    if not active_session:
        # Should not happen if filter works and state is consistent, but safety check
        await db.update_user_state(user_id, "IDLE")
        return

    session_id = active_session["session_id"]

    # Check if already processing (debounce)
    if active_session["status"] == "processing":
        return

    # Try to lock session for processing
    if not await db.set_session_processing(session_id):
        return

    user_text = message.text

    # Save user message
    await db.add_dialogue_message(session_id, "user", user_text)

    # Get context
    history = await db.get_dialogue_history(session_id)

    # Generate response
    try:
        response_data = await ai_client.generate_response(history)
    except Exception as e:
        await logger.aerror("AI Error during response", error=str(e))
        await message.answer("Банкир отошел и забыл про тебя. Попробуй начать сначала (/credit).")
        await db.update_user_state(user_id, "IDLE")
        # Optional: close session as 'failed'
        await db.close_credit_session(session_id, "failed", 0, 0)
        return

    ai_text = response_data["content"]
    completion = response_data["completion_data"]

    # Save assistant message
    await db.add_dialogue_message(session_id, "assistant", ai_text)
    await message.answer(ai_text)

    if completion and completion.get("done"):
        score = completion.get("score", 0)
        reward = completion.get("reward", 0)

        # Update balance
        await db.update_balance(user_id, reward)

        # Log event
        event_id = str(uuid.uuid4())
        await db.add_event(event_id, user_id, "credit_grant", reward, metadata=str(completion))

        # Close session
        await db.close_credit_session(session_id, "completed", score, reward)

        # Reset state
        await db.update_user_state(user_id, "IDLE")

        await message.answer(f"💰 Начислено {reward} монет! Теперь можешь играть.")
