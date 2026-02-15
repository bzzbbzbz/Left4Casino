"""
Heist Service - ежедневный ивент "Ограбление Банка".

Реализует функционал ограбления:
- 1 раз в сутки в случайное время (только в активные часы)
- Все спины слотов наполняют общий банк (котёл)
- Последний игрок забирает весь банк за вычетом комиссии крупье
- Двухфазная адаптивная длительность (Фаза 1: Ограбление, Фаза 2: Тревога)
- Экономика масштабируется относительно вчерашних выигрышей чата
"""

import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytz
import structlog
from aiogram import Bot
from bot.db import Database
from bot.utils.formatters import format_number

logger = structlog.get_logger()


# Сообщения крупье для Фазы 1 (случайный выбор)
PHASE1_MESSAGES = [
    "💰 В банке уже {pot} очков! Кто рискнёт?",
    "🔓 Взломщики набрали {pot} очков! Продолжаем?",
    "💎 Добыча: {pot}! Каждый спин — шанс стать последним!",
    "🃏 Крупье шепчет: «Ещё немного... ещё чуть-чуть...»",
    "💰 {pot} на столе! Жадность — двигатель прогресса!",
    "🏦 Сейфы ломятся! {pot} очков ждут своего хозяина!",
]

# Сообщения для Фазы 2 (каждую минуту)
PHASE2_MESSAGES = [
    "🚔 Сирены приближаются! Торопитесь!",
    "👮 Они уже близко! Хватайте что можете!",
    "🚨 Ещё минута и полиция будет на месте!",
]


@dataclass
class HeistState:
    """Состояние ограбления в одном чате"""

    chat_id: int
    base_value: int  # B для этого ивента
    pot: int  # текущий банк
    pot_cap: int  # порог для досрочной Фазы 2
    seed_amount: int  # seed = B × random(5-10%)
    phase: str  # 'robbery' | 'alarm' | 'ended'
    phase1_end: datetime  # когда заканчивается Фаза 1
    phase2_end: datetime | None  # когда заканчивается Фаза 2
    phase2_duration: int  # длительность Фазы 2 (мин)
    last_spinner_id: int | None = None
    last_spinner_first_name: str | None = None  # Имя вместо никнейма
    last_spin_time: datetime | None = None
    last_announced_spinner_id: int | None = None  # Последний объявленный игрок
    total_spins: int = 0
    participants: set[int] = field(default_factory=set)
    seed_applied: bool = False
    start_time: datetime | None = None
    extended: bool = False  # было ли продление Фазы 1


class HeistService:
    """
    Сервис управления ивентом "Ограбление Банка".

    Функционал:
    - Генерация расписания на сутки (1 случайное время в активные часы)
    - Запуск/завершение ивента
    - Обработка спинов во время ивента
    - Отправка уведомлений и периодических сообщений крупье
    - Двухфазная система с адаптивной длительностью
    """

    def __init__(
        self,
        bot: Bot,
        db: Database,
        config,
        allowed_chat_ids: list[int],
        timezone_str: str = "Asia/Yekaterinburg",
    ):
        self.bot = bot
        self.db = db
        self.config = config
        self.allowed_chat_ids = allowed_chat_ids
        self.timezone = pytz.timezone(timezone_str)

        # Состояние
        self.active_heists: dict[int, HeistState] = {}  # chat_id → state
        self.scheduled_time: datetime | None = None  # запланированное время
        self._schedule_date: datetime | None = None  # дата, на которую сгенерировано расписание

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """Парсит время в формате HH:MM"""
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    def _generate_random_time_in_active_hours(self, date: datetime) -> datetime:
        """Генерирует случайное время в активные часы с запасом на завершение ивента"""
        start_h, start_m = self._parse_time(self.config.active_hours_start)
        end_h, end_m = self._parse_time(self.config.active_hours_end)

        # Запас времени = phase1_max + phase2_max + 10 минут
        reserve_minutes = self.config.phase1_max_minutes + self.config.phase2_max_minutes + 10

        # Период переходит через полночь (например, 08:00 - 02:00)
        if start_h > end_h:
            # Первая часть: start_h:00 до 23:59
            # Вторая часть: 00:00 до end_h:00
            first_part_minutes = (24 - start_h) * 60 - start_m
            second_part_minutes = end_h * 60 + end_m
            total_minutes = first_part_minutes + second_part_minutes - reserve_minutes

            if total_minutes <= 0:
                # Недостаточно времени, используем начало активного периода
                return date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)

            random_minute = random.randint(0, total_minutes - 1)

            if random_minute < first_part_minutes:
                # В первой части (сегодня)
                hour = start_h + (start_m + random_minute) // 60
                minute = (start_m + random_minute) % 60
            else:
                # Во второй части (после полуночи)
                offset = random_minute - first_part_minutes
                hour = offset // 60
                minute = offset % 60
        else:
            # Обычный период в один день
            total_minutes = (end_h - start_h) * 60 + (end_m - start_m) - reserve_minutes

            if total_minutes <= 0:
                return date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)

            random_minute = random.randint(0, total_minutes - 1)
            hour = start_h + (start_m + random_minute) // 60
            minute = (start_m + random_minute) % 60

        return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    async def calculate_base_value(self, chat_id: int) -> int:
        """Рассчитывает B для чата на основе вчерашних выигрышей"""
        now = datetime.now(self.timezone)
        yesterday = now - timedelta(days=1)

        # Вчерашний день: 00:00 - 23:59
        start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_yesterday = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Конвертируем в UTC для запроса к БД
        start_utc = start_of_yesterday.astimezone(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = end_of_yesterday.astimezone(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")

        # Получаем сумму выигрышей
        b_raw = await self.db.get_yesterday_total_won(chat_id, start_utc, end_utc)

        # Fallback если данных нет
        if b_raw < self.config.base_value_fallback:
            b_raw = self.config.base_value_fallback

        # Применяем шум ±15%
        noise_factor = random.uniform(
            1.0 - self.config.base_value_noise_pct / 100,
            1.0 + self.config.base_value_noise_pct / 100,
        )

        b = int(b_raw * noise_factor)

        logger.info(
            "Calculated base value for heist",
            chat_id=chat_id,
            b_raw=b_raw,
            b=b,
            noise_factor=round(noise_factor, 2),
        )

        return b

    def generate_daily_schedule(self) -> datetime | None:
        """
        Генерирует время запуска на текущие сутки.
        Вызывается в 00:00 или при старте бота.
        Возвращает запланированное время или None если ивент отключен.
        """
        if not self.config.enabled:
            self.scheduled_time = None
            return None

        now = datetime.now(self.timezone)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Если расписание уже сгенерировано на сегодня, не перегенерируем
        if self._schedule_date and self._schedule_date.date() == today.date():
            if self.scheduled_time and self.scheduled_time > now:
                return self.scheduled_time
            else:
                # Время уже прошло, сбрасываем
                self.scheduled_time = None
                return None

        # ===== ТЕСТИРОВАНИЕ: Фиксированное время =====
        # random_time = now.replace(hour=20, minute=40, second=0, microsecond=0)
        # ===== КОНЕЦ ТЕСТИРОВАНИЯ =====

        # Генерируем случайное время в активные часы (ЗАКОММЕНТИРОВАНО ДЛЯ ТЕСТА)
        random_time = self._generate_random_time_in_active_hours(today)

        # Если время уже прошло, пропускаем
        if random_time <= now:
            self.scheduled_time = None
            self._schedule_date = today
            logger.info("Heist time already passed for today, skipping")
            return None

        self.scheduled_time = random_time
        self._schedule_date = today

        logger.info(
            "Generated heist schedule",
            scheduled_time=random_time.strftime("%H:%M"),
        )

        return random_time

    async def send_warning(self):
        """Отправляет предупреждение за 10 мин до старта во все чаты"""
        if not self.config.enabled:
            return

        text = (
            "⏰🏦 <b>ВНИМАНИЕ!</b>\n\n"
            "Через 10 минут начнётся Ограбление Банка!\n"
            "Готовьте свои фишки — последний заберёт ВСЁ! 💰"
        )

        for chat_id in self.allowed_chat_ids:
            try:
                await self.bot.send_message(chat_id, text)
            except Exception as e:
                logger.warning(
                    "Failed to send heist warning",
                    chat_id=chat_id,
                    error=str(e),
                )

    async def start_heist(self):
        """Запускает ивент во всех чатах (отдельный банк в каждом)"""
        if not self.config.enabled:
            return

        now = datetime.now(self.timezone)

        # Генерируем длительности фаз
        phase1_duration = random.randint(
            self.config.phase1_min_minutes, self.config.phase1_max_minutes
        )
        phase2_duration = random.randint(
            self.config.phase2_min_minutes, self.config.phase2_max_minutes
        )

        phase1_end = now + timedelta(minutes=phase1_duration)

        for chat_id in self.allowed_chat_ids:
            try:
                # Рассчитываем B для чата
                b = await self.calculate_base_value(chat_id)

                # [START SPEC:HEIST-ECONOMY:pot_cap_and_seed]
                # REQ: pot_cap = B * pot_cap_pct%; seed = B * random(seed_min_pct..seed_max_pct)%
                # Source: HEIST_SPEC.md, секция "Экономика"
                # CRITICAL: Множители влияют на длительность ивента и game balance
                pot_cap = int(b * self.config.pot_cap_pct / 100)
                seed_pct = random.randint(self.config.seed_min_pct, self.config.seed_max_pct)
                seed_amount = int(b * seed_pct / 100)
                # [END SPEC:HEIST-ECONOMY]

                # Создаём состояние
                state = HeistState(
                    chat_id=chat_id,
                    base_value=b,
                    pot=0,
                    pot_cap=pot_cap,
                    seed_amount=seed_amount,
                    phase="robbery",
                    phase1_end=phase1_end,
                    phase2_end=None,
                    phase2_duration=phase2_duration,
                    start_time=now,
                )

                self.active_heists[chat_id] = state

                # Логируем старт
                event_id = str(uuid.uuid4())
                metadata = json.dumps(
                    {
                        "chat_id": chat_id,
                        "base_value": b,
                        "pot_cap": pot_cap,
                        "seed_pct": seed_pct,
                        "phase1_duration_minutes": phase1_duration,
                        "phase2_duration_minutes": phase2_duration,
                    }
                )
                await self.db.add_event(event_id, 0, "heist_start", 0, metadata, chat_id)

                # Отправляем стартовое сообщение
                text = (
                    "🏦💥 <b>ОГРАБЛЕНИЕ БАНКА!</b> 💥🏦\n\n"
                    "Сейф вскрыт! Крутите слоты — вся добыча идёт в общий котёл!\n"
                    "Последний, кто крутанёт, заберёт ВСЁ! 💰\n\n"
                    "<b>Правила:</b>\n"
                    "• Каждый спин 🎰 — ваша ставка уходит в банк\n"
                    "• Выигрыши тоже идут в банк (не вам!)\n"
                    "• Когда ограбление закончится — последний игрок забирает банк"
                )

                await self.bot.send_message(chat_id, text)

                logger.info(
                    "Heist started",
                    chat_id=chat_id,
                    base_value=b,
                    pot_cap=pot_cap,
                    phase1_duration=phase1_duration,
                )

            except Exception as e:
                logger.error(
                    "Failed to start heist in chat",
                    chat_id=chat_id,
                    error=str(e),
                )

    async def process_spin(
        self,
        chat_id: int,
        user_id: int,
        first_name: str,
        bid: int,
        dice_value: int,
        calculated_win: int,
    ) -> dict:
        """
        Обрабатывает спин во время ивента.
        Новая логика: только проигрыши идут в банк, выигрыши — игрокам.
        Возвращает dict с информацией для ответа игроку.
        """
        state = self.active_heists.get(chat_id)
        if not state:
            return {"error": "Heist not active"}

        # Обновляем состояние
        pot_before = state.pot

        # Только проигрыши идут в банк
        if calculated_win == 0:
            state.pot += bid

        pot_after = state.pot

        # Обновляем последнего игрока
        state.last_spinner_id = user_id
        state.last_spinner_first_name = first_name
        state.last_spin_time = datetime.now(self.timezone)
        state.total_spins += 1
        state.participants.add(user_id)

        # Логируем вклад только для проигрышей
        if calculated_win == 0:
            event_id = str(uuid.uuid4())
            metadata = json.dumps(
                {
                    "chat_id": chat_id,
                    "bid": bid,
                    "dice_value": dice_value,
                    "pot_before": pot_before,
                    "pot_after": pot_after,
                }
            )
            await self.db.add_event(
                event_id, user_id, "heist_contribution", -bid, metadata, chat_id
            )

        # Проверяем pot_cap
        if state.phase == "robbery" and state.pot >= state.pot_cap:
            await self.start_alarm_phase(chat_id)

        return {
            "pot": pot_after,
            "calculated_win": calculated_win,
        }

    # [START SPEC:HEIST-PHASES:check_seed_needed]
    # REQ: Через 5 мин после старта если pot = 0 — крупье вносит seed (fallback)
    # Source: HEIST_SPEC.md, "Фаза 1"
    async def check_seed_needed(self, chat_id: int):
        """Проверяет, нужно ли добавить seed (через 5 мин после старта, если pot = 0)"""
        state = self.active_heists.get(chat_id)
        if not state or state.seed_applied or state.pot > 0:
            return

        # Добавляем seed
        state.pot += state.seed_amount
        state.seed_applied = True

        # Логируем
        event_id = str(uuid.uuid4())
        await self.db.add_event(event_id, 0, "heist_seed", state.seed_amount, None, chat_id)

        # Отправляем сообщение
        text = (
            f"😤 Никто? Серьёзно?!\n"
            f"Крупье достаёт {state.seed_amount} из своего кармана и бросает на стол! 💸"
        )

        try:
            await self.bot.send_message(chat_id, text)
        except Exception as e:
            logger.warning("Failed to send seed message", chat_id=chat_id, error=str(e))

    # [END SPEC:HEIST-PHASES]

    async def start_alarm_phase(self, chat_id: int):
        """Запускает Фазу 2 для чата"""
        state = self.active_heists.get(chat_id)
        if not state or state.phase != "robbery":
            return

        now = datetime.now(self.timezone)
        state.phase = "alarm"
        state.phase2_end = now + timedelta(minutes=state.phase2_duration)

        # Формируем сообщение
        last_spinner_mention = ""
        if state.last_spinner_first_name:
            last_spinner_mention = f"\n🏃 Сейчас с добычей уйдёт: {state.last_spinner_first_name}"

        text = (
            "🚨 <b>ТРЕВОГА! Сигнализация сработала!</b> 🚨\n\n"
            "Полиция выехала! Последние минуты!\n"
            "Кто последний крутанёт — тот с добычей! 🏃‍♂️💨\n\n"
            f"💰 В банке: {format_number(state.pot)} очков"
            f"{last_spinner_mention}"
        )

        try:
            await self.bot.send_message(chat_id, text)
        except Exception as e:
            logger.warning("Failed to send alarm message", chat_id=chat_id, error=str(e))

        logger.info(
            "Alarm phase started",
            chat_id=chat_id,
            pot=state.pot,
            phase2_end=state.phase2_end.strftime("%H:%M:%S"),
        )

    # [START SPEC:HEIST-PHASES:check_phase1_end]
    # REQ: По истечении Фазы 1: если pot < min_pot и не продлевали — +5 мин; иначе переход в Фазу 2
    # Source: HEIST_SPEC.md, двухфазная система
    # CRITICAL: Логика перехода и продления влияет на UX и длительность ивента
    async def check_phase1_end(self, chat_id: int):
        """Проверяет, не пора ли завершить Фазу 1"""
        state = self.active_heists.get(chat_id)
        if not state or state.phase != "robbery":
            return

        now = datetime.now(self.timezone)

        if now >= state.phase1_end:
            min_pot = int(state.base_value * self.config.min_pot_pct / 100)

            # Если банк меньше min_pot и продление ещё не было
            if state.pot < min_pot and not state.extended:
                # Продлеваем на 5 минут
                state.phase1_end = now + timedelta(minutes=5)
                state.extended = True

                logger.info(
                    "Phase 1 extended",
                    chat_id=chat_id,
                    pot=state.pot,
                    min_pot=min_pot,
                )
            else:
                # Переходим в Фазу 2
                await self.start_alarm_phase(chat_id)

    # [END SPEC:HEIST-PHASES]

    async def end_heist(self, chat_id: int):
        """Завершает ивент в чате, определяет победителя"""
        state = self.active_heists.get(chat_id)
        if not state:
            return

        state.phase = "ended"

        # Если никто не играл
        if not state.last_spinner_id:
            if state.seed_applied:
                # Был seed, но никто не крутил
                text = (
                    "🏦 Ограбление провалилось!\n"
                    f"Крупье забрал свои {state.seed_amount} очков обратно и ушёл в закат. 🌅"
                )
            else:
                # Вообще никто не пришёл
                text = (
                    "🏦 Ограбление провалилось — никто не пришёл.\n"
                    "Банк вздохнул с облегчением. 😮‍💨"
                )

            try:
                await self.bot.send_message(chat_id, text)
            except Exception:
                pass

            # Логируем
            event_id = str(uuid.uuid4())
            await self.db.add_event(event_id, 0, "heist_no_winner", 0, None, chat_id)

            # Удаляем состояние
            del self.active_heists[chat_id]

            logger.info("Heist ended with no winner", chat_id=chat_id)
            return

        # [START SPEC:HEIST-ECONOMY:commission_and_payout]
        # REQ: commission = pot * commission_pct%; payout = pot - commission (дефляция)
        # Source: HEIST_SPEC.md, секция "Экономика", "Завершение"
        # CRITICAL: Комиссия уничтожается из экономики; не менять без ревью баланса
        commission = int(state.pot * self.config.commission_pct / 100)
        payout = state.pot - commission

        # Выплачиваем победителю
        await self.db.update_balance(state.last_spinner_id, payout)
        # [END SPEC:HEIST-ECONOMY]

        # Логируем выплату
        event_id = str(uuid.uuid4())
        metadata = json.dumps(
            {
                "chat_id": chat_id,
                "total_pot": state.pot,
                "commission_amount": commission,
                "payout": payout,
                "total_spins": state.total_spins,
                "total_participants": len(state.participants),
                "duration_seconds": int(
                    (datetime.now(self.timezone) - state.start_time).total_seconds()
                ),
                "base_value": state.base_value,
            }
        )
        await self.db.add_event(
            event_id, state.last_spinner_id, "heist_win", payout, metadata, chat_id
        )

        # Логируем комиссию
        event_id = str(uuid.uuid4())
        await self.db.add_event(event_id, 0, "heist_commission", -commission, None, chat_id)

        # Отправляем сообщение
        text = (
            "🚔💨 <b>ПОЛИЦИЯ НА МЕСТЕ!</b>\n\n"
            f"🏃‍♂️ {state.last_spinner_first_name} успел скрыться с добычей!\n\n"
            f"💰 Награда: <b>{format_number(payout)}</b> очков\n"
            f"🏦 Всего в банке было: {format_number(state.pot)}\n"
            f"🃏 Доля крупье ({self.config.commission_pct}%): {format_number(commission)}"
        )

        try:
            await self.bot.send_message(chat_id, text)
        except Exception as e:
            logger.warning("Failed to send heist end message", chat_id=chat_id, error=str(e))

        # Удаляем состояние
        del self.active_heists[chat_id]

        logger.info(
            "Heist ended with winner",
            chat_id=chat_id,
            winner_id=state.last_spinner_id,
            payout=payout,
            total_pot=state.pot,
        )

    async def send_croupier_message(self, chat_id: int):
        """Отправляет периодическое сообщение крупье"""
        state = self.active_heists.get(chat_id)
        if not state:
            return

        if state.phase == "robbery":
            # Фаза 1 - случайное сообщение из пула
            msg_template = random.choice(PHASE1_MESSAGES)
            msg = msg_template.format(pot=format_number(state.pot))

            # Добавляем информацию о последнем игроке ТОЛЬКО если он изменился
            if (
                state.last_spinner_first_name
                and state.last_spinner_id != state.last_announced_spinner_id
            ):
                msg += f"\n🏃 Сейчас с добычей уйдёт {state.last_spinner_first_name}!"
                state.last_announced_spinner_id = state.last_spinner_id
            elif state.last_spinner_id == state.last_announced_spinner_id:
                # Последний игрок не изменился, не отправляем сообщение
                return

        elif state.phase == "alarm":
            # Фаза 2 - сообщения тревоги
            msg = random.choice(PHASE2_MESSAGES)

        else:
            return

        try:
            await self.bot.send_message(chat_id, msg)
        except Exception as e:
            logger.warning("Failed to send croupier message", chat_id=chat_id, error=str(e))

    def is_active(self, chat_id: int) -> bool:
        """Проверяет, активен ли ивент в чате"""
        state = self.active_heists.get(chat_id)
        return state is not None and state.phase in ("robbery", "alarm")

    def get_heist_state(self, chat_id: int) -> HeistState | None:
        """Возвращает состояние ивента в чате"""
        return self.active_heists.get(chat_id)
