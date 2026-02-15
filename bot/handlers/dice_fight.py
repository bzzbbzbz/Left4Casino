"""
PvP Dice Fights Handler
Allows players to challenge each other to dice duels
"""

import html
import json
import random
import uuid

from aiogram import Bot, F, Router
from aiogram.enums import DiceEmoji
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config_reader import DiceFightsConfig
from bot.db import Database
from bot.utils.formatters import format_number

router = Router()

# ==================== PHRASES ====================

FIGHT_WIN_PHRASES = [
    "💪 {winner} УНИЧТОЖИЛ {loser}! Забирает {amount} очков!",
    "🏆 {winner} показал, кто тут босс! +{amount} в карман!",
    "😎 {winner} оставил {loser} без штанов! Лёгкие {amount} очков!",
    "🔥 FATALITY! {winner} выносит {loser} и забирает {amount}!",
    "👑 {winner} — новый король ринга! {loser} отдаёт {amount} очков!",
    "🎰 Удача на стороне {winner}! {loser} плачет и отдаёт {amount}!",
    "⚡️ {winner} бросил кубик судьбы и забрал {amount} у {loser}!",
    "🥊 Нокаут! {winner} отправляет {loser} в финансовый нокдаун!",
    "💸 {loser} спонсирует победу {winner} на {amount} очков!",
    "🎯 Точно в цель! {winner} снимает {amount} с {loser}!",
]

FIGHT_DEBT_PHRASES = [
    "💀 {loser} не только проиграл, но ещё и остался должен {debt} очков!",
    "📉 {loser} ушёл в минус! Долг: {debt} очков. Коллекторы уже в пути!",
    "🏚 {loser} теперь должен {winner} целых {debt} очков! Готовь почку!",
    "😱 {loser} влез в долговую яму на {debt} очков!",
    "🔻 Кредитная история {loser} пополнилась долгом в {debt} очков!",
]

FIGHT_DRAW_PHRASES = [
    "🤝 Ничья! Оба выбросили {roll}. Деньги остаются при своих!",
    "⚖️ Судьба решила: {roll} = {roll}. Расходимся мирно!",
    "🎭 Боги рандома пошутили — ничья {roll}:{roll}!",
    "🪢 Узел на кубиках! {roll} против {roll}. Никто не в обиде!",
    "😐 Скучная ничья {roll}:{roll}. Попробуйте ещё раз!",
]

TAKE_SUCCESS_PHRASES = [
    "💰 Взыскано {amount} очков с @{debtor}!",
    "🤑 {amount} очков изъято у @{debtor}!",
    "💵 Коллектор доволен: {amount} очков получено от @{debtor}!",
    "🏦 Долг частично погашен: -{amount} с @{debtor}!",
]


# ==================== KEYBOARDS ====================


def get_challenge_keyboard(challenge_id: str, initiator_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ Принять вызов", callback_data=f"dice_accept:{challenge_id}"
                ),
                InlineKeyboardButton(
                    text="🚫", callback_data=f"dice_cancel:{challenge_id}:{initiator_id}"
                ),
            ]
        ]
    )


# ==================== FILTERS ====================


class ActiveDuelFilter(Filter):
    """Filter for dice rolls from duel participants"""

    async def __call__(self, message: Message, db: Database) -> bool | dict:
        if message.chat.type not in ("group", "supergroup"):
            return False

        challenge = await db.get_accepted_challenge_for_user(message.from_user.id, message.chat.id)
        if challenge:
            return {"active_challenge": challenge}
        return False


# ==================== COMMANDS ====================


@router.message(Command("dice"))
async def cmd_dice(
    message: Message, command: CommandObject, db: Database, dice_fights_config: DiceFightsConfig
):
    """Create a new dice challenge"""
    # Check group chat
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Драки работают только в групповых чатах!")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Register user if needed
    if message.from_user.username:
        await db.register_user(user_id, message.from_user.username)

    # Parse bet amount or use last bet
    if not command.args:
        last_bet = await db.get_last_dice_bet(user_id)
        if last_bet is None:
            await message.reply("Использование: /dice [ставка]\nПример: /dice 50")
            return
        bet = last_bet
    else:
        try:
            bet = int(command.args.split()[0])
        except ValueError:
            await message.reply("Ставка должна быть числом!")
            return

    if bet < dice_fights_config.min_bet:
        await message.reply(f"Минимальная ставка: {dice_fights_config.min_bet}")
        return

    # Get balance and current debt
    balance = await db.get_balance(user_id, 50)
    current_debt = await db.get_total_debt(user_id, chat_id)

    # Check max bet: balance + (max_debt - current_debt)
    # Player can't exceed total debt of max_debt
    max_debt = dice_fights_config.max_debt
    available_debt = max(0, max_debt - current_debt)
    max_bet = max(0, balance) + available_debt

    if bet > max_bet:
        if current_debt > 0:
            await message.reply(
                f"Максимальная ставка: {format_number(max_bet)} (баланс {format_number(balance)} + доступный долг {format_number(available_debt)}, уже должен {format_number(current_debt)})"
            )
        else:
            await message.reply(
                f"Максимальная ставка: {format_number(max_bet)} (баланс {format_number(balance)} + возможный долг {format_number(max_debt)})"
            )
        return

    # Check if would exceed max debt
    potential_new_debt = max(0, bet - balance)
    if current_debt + potential_new_debt > max_debt:
        await message.reply(
            f"Нельзя! Общий долг превысит {max_debt} очков (уже должен {current_debt})"
        )
        return

    # Check for existing active challenge
    existing = await db.get_active_challenge_by_user(user_id, chat_id)
    if existing:
        await message.reply("У вас уже есть активный вызов! Дождитесь его завершения или отмените.")
        return

    # Save last bet
    await db.set_last_dice_bet(user_id, bet)

    # Determine if going into debt
    going_debt = bet > balance

    # Create challenge
    challenge_id = str(uuid.uuid4())
    nickname = message.from_user.username
    first_name = message.from_user.first_name
    display_name = nickname or first_name
    safe_display = html.escape(str(display_name))

    # Build message
    debt_warning = ""
    if going_debt:
        debt_warning = f"\n⚠️ <b>Игрок идёт в долг!</b> (баланс: {format_number(balance)})"

    # Use @username if available, otherwise just name
    name_display = f"@{safe_display}" if nickname else safe_display

    challenge_text = (
        f"🎲 <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
        f"👤 {name_display} ставит <b>{format_number(bet)}</b> очков!"
        f"{debt_warning}\n\n"
        f"💡 Нажми кнопку, чтобы принять вызов.\n"
        f"⏱ Вызов истекает через {dice_fights_config.challenge_timeout_minutes} минут."
    )

    # Send message with keyboard
    sent_msg = await message.answer(
        challenge_text, reply_markup=get_challenge_keyboard(challenge_id, user_id)
    )

    # Save challenge to DB
    await db.create_dice_challenge(
        challenge_id=challenge_id,
        chat_id=chat_id,
        initiator_id=user_id,
        nickname=nickname,
        first_name=first_name,
        bet=bet,
        going_debt=going_debt,
        message_id=sent_msg.message_id,
    )


@router.callback_query(F.data.startswith("dice_cancel:"))
async def on_dice_cancel(callback: CallbackQuery, db: Database):
    """Cancel a dice challenge"""
    parts = callback.data.split(":")
    challenge_id = parts[1]
    initiator_id = int(parts[2])

    # Only initiator can cancel
    if callback.from_user.id != initiator_id:
        await callback.answer("Только инициатор может отменить вызов!", show_alert=True)
        return

    # Check challenge exists and is pending
    challenge = await db.get_challenge(challenge_id)
    if not challenge or challenge["status"] != "pending":
        await callback.answer("Вызов уже не активен!", show_alert=True)
        return

    # Cancel
    await db.cancel_challenge(challenge_id)

    # Update message
    nickname = challenge["initiator_nickname"] or "Игрок"
    await callback.message.edit_text(
        f"🚫 <b>Вызов отменён</b>\n\n@{html.escape(str(nickname))} передумал драться."
    )
    await callback.answer("Вызов отменён")


@router.callback_query(F.data.startswith("dice_accept:"))
async def on_dice_accept(
    callback: CallbackQuery, db: Database, dice_fights_config: DiceFightsConfig
):
    """Accept a dice challenge"""
    challenge_id = callback.data.split(":")[1]

    # Get challenge
    challenge = await db.get_challenge(challenge_id)
    if not challenge:
        await callback.answer("Вызов не найден!", show_alert=True)
        return

    if challenge["status"] != "pending":
        await callback.answer("Вызов уже не активен!", show_alert=True)
        return

    opponent_id = callback.from_user.id
    initiator_id = challenge["initiator_id"]
    bet = challenge["bet_amount"]
    chat_id = challenge["chat_id"]

    # Can't accept own challenge
    if opponent_id == initiator_id:
        await callback.answer("Нельзя драться с самим собой!", show_alert=True)
        return

    # Register opponent if needed
    if callback.from_user.username:
        await db.register_user(opponent_id, callback.from_user.username)

    # Check opponent balance and current debt
    opponent_balance = await db.get_balance(opponent_id, 50)
    opponent_current_debt = await db.get_total_debt(opponent_id, chat_id)
    max_debt = dice_fights_config.max_debt
    available_debt = max(0, max_debt - opponent_current_debt)
    max_affordable = max(0, opponent_balance) + available_debt

    if bet > max_affordable:
        if opponent_current_debt > 0:
            await callback.answer(
                f"Баланс {format_number(opponent_balance)} + доступный долг {format_number(available_debt)} = {format_number(max_affordable)}. Уже должен {format_number(opponent_current_debt)}!",
                show_alert=True,
            )
        else:
            await callback.answer(
                f"Баланс ({format_number(opponent_balance)}) + макс. долг ({format_number(max_debt)}) = {format_number(max_affordable)}. Ставка слишком высока!",
                show_alert=True,
            )
        return

    # Check existing challenge for opponent
    existing = await db.get_active_challenge_by_user(opponent_id, chat_id)
    if existing and existing["challenge_id"] != challenge_id:
        await callback.answer("У вас уже есть активный вызов!", show_alert=True)
        return

    # Accept challenge
    opponent_nickname = callback.from_user.username
    opponent_first_name = callback.from_user.first_name
    success = await db.accept_challenge(
        challenge_id, opponent_id, opponent_nickname, opponent_first_name
    )

    if not success:
        await callback.answer("Не удалось принять вызов!", show_alert=True)
        return

    # Update message - use first_name for display
    initiator_name = (
        challenge.get("initiator_first_name") or challenge["initiator_nickname"] or "Игрок"
    )
    opponent_name = opponent_first_name

    duel_text = (
        f"⚔️ <b>ДУЭЛЬ НАЧАЛАСЬ!</b>\n\n"
        f"👤 {html.escape(str(initiator_name))} vs 👤 {html.escape(str(opponent_name))}\n"
        f"💰 Ставка: <b>{format_number(bet)}</b> очков\n\n"
        f"Отправьте 🎲 в чат для броска!\n"
        f"⏱ Время: {dice_fights_config.roll_timeout_minutes} минут"
    )

    await callback.message.edit_text(duel_text)
    await callback.answer("Вы приняли вызов! Бросайте кубик 🎲")


@router.message(F.dice.emoji == DiceEmoji.DICE, ActiveDuelFilter())
async def on_dice_roll(message: Message, db: Database, active_challenge: dict, bot: Bot):
    """Handle dice roll from duel participant"""
    user_id = message.from_user.id
    challenge_id = active_challenge["challenge_id"]
    roll_value = message.dice.value

    # Check if user already rolled
    is_initiator = user_id == active_challenge["initiator_id"]
    already_rolled = (is_initiator and active_challenge["initiator_roll"] is not None) or (
        not is_initiator and active_challenge["opponent_roll"] is not None
    )

    if already_rolled:
        return  # Silently ignore duplicate rolls

    # Record the roll
    await db.record_roll(challenge_id, user_id, roll_value)

    # Get updated challenge
    challenge = await db.get_challenge(challenge_id)

    # Check if both rolled
    if challenge["initiator_roll"] is not None and challenge["opponent_roll"] is not None:
        await process_duel_result(db, bot, challenge, message.chat.id)


# ==================== RESULT PROCESSING ====================


async def process_duel_result(db: Database, bot: Bot, challenge: dict, chat_id: int):
    """Process the result of a completed duel"""
    initiator_id = challenge["initiator_id"]
    opponent_id = challenge["opponent_id"]
    initiator_roll = challenge["initiator_roll"]
    opponent_roll = challenge["opponent_roll"]
    bet = challenge["bet_amount"]
    challenge_id = challenge["challenge_id"]

    # Use first_name for display (like bankruptcy messages)
    initiator_name = (
        challenge.get("initiator_first_name") or challenge["initiator_nickname"] or "Игрок1"
    )
    opponent_name = (
        challenge.get("opponent_first_name") or challenge["opponent_nickname"] or "Игрок2"
    )

    # Determine winner
    if initiator_roll > opponent_roll:
        winner_id = initiator_id
        loser_id = opponent_id
        winner_name = initiator_name
        loser_name = opponent_name
        winner_roll = initiator_roll
        loser_roll = opponent_roll
    elif opponent_roll > initiator_roll:
        winner_id = opponent_id
        loser_id = initiator_id
        winner_name = opponent_name
        loser_name = initiator_name
        winner_roll = opponent_roll
        loser_roll = initiator_roll
    else:
        # Draw
        winner_id = None

    # Complete challenge in DB
    await db.complete_challenge(challenge_id, winner_id)

    if winner_id is None:
        # Draw - no money changes, single line message
        phrase = random.choice(FIGHT_DRAW_PHRASES).format(roll=initiator_roll)
        result_text = phrase

        # Log draw events
        metadata = json.dumps(
            {
                "challenge_id": challenge_id,
                "opponent_id": opponent_id if initiator_id != opponent_id else initiator_id,
                "rolls": [initiator_roll, opponent_roll],
            }
        )
        await db.add_event(
            str(uuid.uuid4()), initiator_id, "dice_challenge_draw", 0, metadata, chat_id
        )
        await db.add_event(
            str(uuid.uuid4()), opponent_id, "dice_challenge_draw", 0, metadata, chat_id
        )

    else:
        # Winner determined - process money
        loser_balance = await db.get_balance(loser_id)

        # Calculate actual transfer and debt
        if loser_balance >= bet:
            # Loser can pay full amount
            actual_transfer = bet
            debt_amount = 0
        else:
            # Loser goes into debt
            actual_transfer = max(0, loser_balance)
            debt_amount = bet - actual_transfer

        # Update balances
        if actual_transfer > 0:
            await db.update_balance(loser_id, -actual_transfer)
            await db.update_balance(winner_id, actual_transfer)

        # Create debt if needed
        if debt_amount > 0:
            await db.create_or_update_debt(loser_id, winner_id, debt_amount, chat_id, challenge_id)

        # Build single-line result text with first_name (like bankruptcy)
        phrase = random.choice(FIGHT_WIN_PHRASES).format(
            winner=html.escape(str(winner_name)),
            loser=html.escape(str(loser_name)),
            amount=format_number(bet),
        )
        result_text = phrase

        # Add debt info on same line if applicable
        if debt_amount > 0:
            result_text += f" Долг: {format_number(debt_amount)}."

        # Log events
        metadata = json.dumps(
            {
                "challenge_id": challenge_id,
                "opponent_id": loser_id,
                "rolls": [winner_roll, loser_roll],
                "debt": debt_amount,
            }
        )
        await db.add_event(
            str(uuid.uuid4()), winner_id, "dice_challenge_win", actual_transfer, metadata, chat_id
        )

        metadata = json.dumps(
            {
                "challenge_id": challenge_id,
                "opponent_id": winner_id,
                "rolls": [loser_roll, winner_roll],
                "debt": debt_amount,
            }
        )
        await db.add_event(
            str(uuid.uuid4()), loser_id, "dice_challenge_loss", -actual_transfer, metadata, chat_id
        )

    # Send single-line result message
    await bot.send_message(chat_id, result_text)


# ==================== AUTO-ROLL TIMEOUT ====================


async def auto_roll_for_timeout(db: Database, bot: Bot, challenge: dict):
    """Handle timeout - auto-roll for players who didn't roll"""
    challenge_id = challenge["challenge_id"]
    chat_id = challenge["chat_id"]

    initiator_id = challenge["initiator_id"]
    opponent_id = challenge["opponent_id"]
    # Use first_name for display
    initiator_name = (
        challenge.get("initiator_first_name") or challenge["initiator_nickname"] or "Игрок1"
    )
    opponent_name = (
        challenge.get("opponent_first_name") or challenge["opponent_nickname"] or "Игрок2"
    )

    messages = []

    # Auto-roll for initiator if needed
    if challenge["initiator_roll"] is None:
        roll = random.randint(1, 6)
        await db.record_roll(challenge_id, initiator_id, roll)
        messages.append(
            f"⏰ {html.escape(str(initiator_name))} не успел бросить кубик! Бот бросает за него: 🎲 <b>{roll}</b>"
        )

    # Auto-roll for opponent if needed
    if challenge["opponent_roll"] is None:
        roll = random.randint(1, 6)
        await db.record_roll(challenge_id, opponent_id, roll)
        messages.append(
            f"⏰ {html.escape(str(opponent_name))} не успел бросить кубик! Бот бросает за него: 🎲 <b>{roll}</b>"
        )

    # Send timeout messages
    if messages:
        await bot.send_message(chat_id, "\n".join(messages))

    # Get updated challenge and process result
    updated_challenge = await db.get_challenge(challenge_id)
    await process_duel_result(db, bot, updated_challenge, chat_id)


# ==================== /TAKE COMMAND ====================


@router.message(Command("take"))
async def cmd_take(message: Message, command: CommandObject, db: Database):
    """Collect debt from a player"""
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("Команда работает только в групповых чатах!")
        return

    if not command.args:
        await message.reply("Использование: /take [сумма] @username\nПример: /take 50 @player")
        return

    parts = command.args.split()

    # Parse amount
    try:
        amount = int(parts[0])
    except ValueError:
        await message.reply("Сумма должна быть числом!")
        return

    if amount <= 0:
        await message.reply("Сумма должна быть положительной!")
        return

    creditor_id = message.from_user.id
    chat_id = message.chat.id
    debtor_id = None
    debtor_nickname = None

    # Find debtor - by reply or by username
    if message.reply_to_message:
        debtor_id = message.reply_to_message.from_user.id
        debtor_nickname = (
            message.reply_to_message.from_user.username
            or message.reply_to_message.from_user.first_name
        )
    elif len(parts) > 1:
        username = parts[1]
        if username.startswith("@"):
            user = await db.get_user_by_nickname(username)
            if user:
                debtor_id = user["user_id"]
                debtor_nickname = user["nickname"]
            else:
                await message.reply("Пользователь не найден!")
                return
        else:
            await message.reply("Укажите @username должника!")
            return
    else:
        await message.reply("Укажите должника (/take X @username)!")
        return

    if debtor_id == creditor_id:
        await message.reply("Нельзя взыскать долг с самого себя!")
        return

    # Check debt exists
    debt = await db.get_debt(chat_id, debtor_id, creditor_id)
    if not debt or debt["amount"] <= 0:
        await message.reply("Этот игрок тебе ничего не должен!")
        return

    # Check amount
    if amount > debt["amount"]:
        await message.reply(
            f"Долг составляет только {format_number(debt['amount'])} очков. Нельзя забрать больше!"
        )
        return

    # Try to collect
    result = await db.collect_debt(creditor_id, debtor_id, amount, chat_id)

    if result[0]:  # Success
        actual_amount = result[1]
        remaining_debt = result[2]

        phrase = random.choice(TAKE_SUCCESS_PHRASES).format(
            amount=format_number(actual_amount), debtor=html.escape(str(debtor_nickname))
        )

        debt_status = ""
        if remaining_debt > 0:
            debt_status = f"\n📋 Остаток долга: {format_number(remaining_debt)}"
        else:
            debt_status = "\n✅ Долг полностью погашен!"

        creditor_balance = await db.get_balance(creditor_id)

        await message.reply(
            f"{phrase}{debt_status}\n💰 Твой баланс: {format_number(creditor_balance)}"
        )
    else:
        error_msg = result[1]
        if "нет средств" in error_msg.lower():
            debtor_balance = await db.get_balance(debtor_id)
            await message.reply(
                f"У @{html.escape(str(debtor_nickname))} баланс {format_number(debtor_balance)}. Ждите, пока заработает!"
            )
        else:
            await message.reply(f"Ошибка: {error_msg}")
