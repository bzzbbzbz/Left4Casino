import asyncio
import html
import random
import uuid
from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ContentType, DiceEmoji
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from bot.config_reader import GameConfig
from bot.db import Database
from bot.dice_check import get_score_change, get_super_jackpot
from bot.models.events import create_event
from bot.services.happy_moment import HappyMomentService
from bot.services.heist import HeistService
from bot.utils.formatters import format_number

router = Router()


async def delete_message_later(message: Message, delay: int = 60):
    """Удаляет сообщение через delay секунд."""
    await asyncio.sleep(delay)
    with suppress(TelegramBadRequest):
        await message.delete()


# Обработчик команды /balance
@router.message(Command("balance"))
async def cmd_balance(message: Message, db: Database, game_config: GameConfig):
    if not message.from_user:
        return
    user_id = message.from_user.id

    if message.from_user.username:
        await db.register_user(user_id, message.from_user.username)

    # Получаем баланс (или начальный, если пользователя нет)
    balance = await db.get_balance(user_id, game_config.starting_points)
    await message.reply(f"Ваш баланс: {format_number(balance)}")


# Обработчик команды /stats
@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database):
    if not message.from_user:
        return

    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Эта команда работает только в группах.")
        return

    target_user_id = message.from_user.id
    target_nickname = message.from_user.username or "unknown"

    command_parts = (message.text or "").split(maxsplit=1)
    target_username = command_parts[1].strip() if len(command_parts) > 1 else None

    if target_username:
        user = await db.get_user_by_nickname(target_username)
        if user is None:
            await message.reply(f"Пользователь {html.escape(target_username)} не найден.")
            return
        target_user_id = user["user_id"]
        target_nickname = user.get("nickname") or target_nickname

    top_users = await db.get_top_users_in_group(message.chat.id, limit=1000)
    user_row = next((u for u in top_users if u["user_id"] == target_user_id), None)
    rank = next(
        (idx for idx, u in enumerate(top_users, start=1) if u["user_id"] == target_user_id), None
    )

    balance = await db.get_balance(target_user_id, 50)
    games = user_row.get("games_played", 0) if user_row else 0
    won = user_row.get("total_won", 0) if user_row else 0
    lost = user_row.get("total_lost", 0) if user_row else 0
    bankruptcy = user_row.get("bankruptcy_count", 0) if user_row else 0

    safe_nickname = html.escape(str(target_nickname))
    text = (
        f"📊 <b>Статистика игрока {safe_nickname}</b>\n\n"
        f"💰 Баланс: {format_number(balance)}\n"
        f"🎰 Всего игр: {format_number(games)}\n"
        f"🤑 Выиграно очков: {format_number(won)}\n"
        f"📉 Потрачено очков: {format_number(lost)}\n"
        f"💀 Банкротств: {format_number(bankruptcy)}\n"
        f"🏅 Позиция в рейтинге: {rank or '—'}"
    )
    await message.reply(text)


def _build_top_text(
    top_users: list[dict], caller_id: int, chat_title: str, max_display: int = 10
) -> str:
    if not top_users:
        return "В этом чате пока нет активных игроков."

    chat_title_safe = html.escape(chat_title)
    lines = [f"🏆 <b>Топ игроков чата {chat_title_safe}:</b>\n"]
    displayed_users = top_users[:max_display]

    for idx, user in enumerate(displayed_users, start=1):
        nickname = user["nickname"] or "Безымянный"
        balance = user["balance"]
        games = user.get("games_played", 0)
        won = user.get("total_won", 0)
        lost = user.get("total_lost", 0)
        bankruptcy = user.get("bankruptcy_count", 0)

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, "")
        place = f"{idx}. {medal}" if medal else f"{idx}."

        # Основная строка с именем и балансом
        lines.append(
            f"{place} <b>{html.escape(str(nickname))}</b> — {format_number(balance)} очков"
        )

        # Детальная статистика (если есть игры)
        if games > 0:
            # Расчет winrate
            wr = (won / (won + lost) * 100) if (won + lost) > 0 else 0.0

            lines.append(f"      🎰 Всего игр: {format_number(games)}")
            lines.append(
                f"      📈 Выиграно очков: {format_number(won)} | "
                f"Потрачено: {format_number(lost)} | "
                f"WR: {wr:.2f}%"
            )
            lines.append(f"      💀 Банкротств: {format_number(bankruptcy)}")

        # Пустая строка между игроками (кроме последнего)
        if idx < len(displayed_users):
            lines.append("")

    caller_rank = next(
        (idx for idx, user in enumerate(top_users, start=1) if user["user_id"] == caller_id), None
    )
    if caller_rank and caller_rank > 10:
        caller_user = top_users[caller_rank - 1]
        caller_name = html.escape(str(caller_user["nickname"] or "Безымянный"))
        caller_balance = format_number(caller_user["balance"])
        lines.append(f"👤 Ты: {caller_rank}. <b>{caller_name}</b> — {caller_balance} очков")

    return "\n".join(lines)


@router.message(Command("top"))
async def cmd_top(message: Message, db: Database):
    if not message.from_user:
        return

    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Эта команда работает только в группах.")
        return

    top_users = await db.get_top_users_in_group(message.chat.id, limit=1000)
    text = _build_top_text(top_users, message.from_user.id, message.chat.title or "Unknown Group")
    await message.reply(text)


# Обработчик броска кубика
@router.message(F.content_type == ContentType.DICE, F.dice.emoji == DiceEmoji.SLOT_MACHINE)
async def on_dice_roll(
    message: Message,
    db: Database,
    game_config: GameConfig,
    happy_moment_service: HappyMomentService,
    heist_service: HeistService,
):
    # Check if forwarded
    if (
        message.forward_date
        or message.forward_from
        or message.forward_from_chat
        or getattr(message, "forward_origin", None)
    ):
        return

    # Игнорируем, если сообщение не от пользователя
    if not message.from_user:
        return

    user_id = message.from_user.id

    if message.from_user.username:
        await db.register_user(user_id, message.from_user.username)

    # Получаем текущий баланс
    current_balance = await db.get_balance(user_id, game_config.starting_points)

    # ПРОВЕРКА НА БАНКРОТА: Если баланс <= 0, удаляем сообщение
    if current_balance <= 0:
        with suppress(TelegramBadRequest):
            await message.delete()
        return

    # Получаем ставку пользователя
    user_bid = await db.get_bid(user_id)

    # Проверяем, хватает ли денег на ставку
    if current_balance < user_bid:
        await message.reply(
            f"Ваш баланс ({format_number(current_balance)}) меньше текущей ставки ({format_number(user_bid)}). Снизьте ставку командой /bid или пополните баланс."
        )
        return

    dice_value = message.dice.value

    # Считаем изменение очков
    score_change = get_score_change(dice_value)

    # Супер Джекпот логика
    super_multiplier = 1
    jackpot_name = None
    if score_change > 0:
        super_multiplier, jackpot_name = get_super_jackpot()

    # [START SPEC:HAPPY-MOMENT:apply_multiplier]
    # REQ: Итоговый выигрыш = базовые_очки × bid × jackpot_multiplier × happy_moment_multiplier
    # Source: HAPPY_MOMENT_SPEC.md, секция "Взаимодействие с игровой механикой"
    # CRITICAL: Множитель "счастливого мига" применяется поверх джекпот-множителя
    happy_multiplier = 1.0
    happy_info = None
    if score_change > 0:
        happy_multiplier = happy_moment_service.get_active_multiplier() or 1.0
        happy_info = happy_moment_service.get_active_moment_info()

    actual_change = int(score_change * user_bid * super_multiplier * happy_multiplier)
    # [END SPEC:HAPPY-MOMENT]

    # [START SPEC:HEIST-SPINS:process_spin]
    # REQ: Только проигрыши идут в банк, выигрыши — игрокам
    # Source: HEIST_SPEC.md, секция "Механика спинов"
    # CRITICAL: Метод heist_service.process_spin обновляет состояние ивента
    heist_info = None
    if heist_service.is_active(message.chat.id):
        heist_info = await heist_service.process_spin(
            chat_id=message.chat.id,
            user_id=user_id,
            first_name=message.from_user.first_name,
            bid=user_bid,
            dice_value=dice_value,
            calculated_win=actual_change,
        )
    # [END SPEC:HEIST-SPINS]

    new_balance = current_balance + actual_change

    # Обновляем баланс в БД
    await db.set_balance(user_id, new_balance)

    # Логируем событие (Pydantic model)
    event_type = "win" if actual_change > 0 else "loss"
    if happy_info and actual_change > 0:
        event_type = "happy_moment_win"

    metadata_dict = {
        "dice_value": dice_value,
        "bid": user_bid,
        "base_score_change": score_change,
        "super_jackpot_multiplier": super_multiplier,
    }

    if happy_info and actual_change > 0:
        metadata_dict.update(
            {
                "happy_moment_multiplier": happy_multiplier,
                "happy_moment_name": happy_info["name"],
                "duration_minutes": happy_info["duration_minutes"],
                "base_win": score_change,  # redundant but follows spec REQ
            }
        )

    if heist_info:
        metadata_dict["during_heist"] = True
        metadata_dict["heist_pot_after"] = heist_info["pot"]

    event = create_event(
        event_type=event_type,
        event_id=str(uuid.uuid4()),
        user_id=user_id,
        amount=actual_change,
        metadata=metadata_dict,
        chat_id=message.chat.id,
    )
    await db.add_event_from_model(event)

    # Обновляем статистику
    is_bankruptcy = new_balance <= 0
    await db.update_user_stats(user_id, actual_change, is_bankruptcy=is_bankruptcy)

    if is_bankruptcy:
        # Record explicit bankruptcy event for daily stats
        await db.add_event(str(uuid.uuid4()), user_id, "bankruptcy", 0, chat_id=message.chat.id)

    # Логика отправки сообщений

    # 1. Выигрышная комбинация (score_change > 0)
    if actual_change > 0:
        if super_multiplier > 1 or happy_multiplier > 1.0:
            header_parts = []
            if super_multiplier > 1:
                if super_multiplier == 2:
                    header_parts.append("🔥 <b>SUPER JACKPOT!</b>")
                elif super_multiplier == 3:
                    header_parts.append("⚡️ <b>MEGA WIN!</b>")
                elif super_multiplier == 5:
                    header_parts.append("🚀 <b>COSMIC JACKPOT!</b>")
                else:  # 10
                    header_parts.append("👑 <b>LEGENDARY WIN!</b>")

            if happy_multiplier > 1.0:
                header_parts.append(f"✨ <b>{happy_info['name']}!</b>")

            header = " + ".join(header_parts)

            # Build multiplier display
            multiplier_parts = []
            if super_multiplier > 1:
                multiplier_parts.append(f"x{super_multiplier}")
            if happy_multiplier > 1.0:
                multiplier_parts.append(f"x{happy_multiplier}")

            multiplier_text = " × ".join(multiplier_parts)

            msg_text = (
                f"{header}\n"
                f"Вы выиграли {format_number(user_bid)} {multiplier_text} = <b>{format_number(actual_change)}</b> очков! "
                f"Ваш баланс: {format_number(new_balance)}"
            )
            await message.reply(msg_text)
        else:
            await message.reply(
                f"Вы выиграли {format_number(actual_change)} очков! Ваш баланс: {format_number(new_balance)}"
            )

    # 2. Банкрот (баланс стал <= 0, но был > 0)
    elif new_balance <= 0:
        player_name = html.escape(message.from_user.first_name)
        bankrupt_phrases = [
            "Вы банкрот! Звоните в екапусту или заложите квартиру",
            "ВЫ — БАНКРОТ!",
            "Поздравляем! Вы успешно достигли финансового дна. 📉",
            "Ваш баланс ушел в отрицательные значения, как и настроение вашего банкира. 💸",
            "Гейм овер. Коллекторы уже выехали. 🚗💨",
            "Кажется, удача взяла выходной. Ваш баланс: 0. 🤷‍♂️",
            "Вам пора открывать сбор средств на доширак. 🍜",
            f"{player_name} собирается в понедельник начать жизнь с нуля. Так бывает после проведенного воскресенья в казино.",
            "Добро пожаловать в клуб анонимных банкротов.",
            f"Сначала {player_name} играл в казино, а потом - на гармошке у прохожих на виду...",
            f"{player_name} из богатой семьи сходил в казино и стал из небогатой.",
            "Иди работать или клянчить фишки у друзей.",
            "Друзья! Подкиньте нищему на додеп.",
            "Упс! Вы всё пролудили и вам пора работать.",
        ]
        await message.reply(random.choice(bankrupt_phrases))

    # 3. Обычный проигрыш - удаляем сообщение через минуту
    else:
        asyncio.create_task(delete_message_later(message))
