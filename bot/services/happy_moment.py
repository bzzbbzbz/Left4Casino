"""
Happy Moment Service - временный бонусный период с множителем выигрышей в слотах.

Реализует функционал "Счастливого мига":
- 2 раза в сутки в случайное время
- Чем короче период, тем выше множитель
- 90% вероятность в активное время (08:00-02:00), 10% ночью
"""

import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz
import structlog
from aiogram import Bot

from bot.db import Database

logger = structlog.get_logger()


# Названия для случайного выбора
MOMENT_NAMES = [
    "Счастливый миг",
    "Золотой час",
    "Бонус-тайм",
    "Джекпот-раш",
    "Звёздный час",
    "Фортуна улыбается",
    "Время удачи",
    "Щедрый момент",
]


@dataclass
class HappyMomentTier:
    """Один уровень счастливого мига"""

    duration_minutes: int
    multiplier: float


@dataclass
class ScheduledMoment:
    """Запланированный счастливый миг"""

    scheduled_time: datetime
    tier: HappyMomentTier
    name: str


@dataclass
class ActiveMoment:
    """Текущий активный счастливый миг"""

    start_time: datetime
    end_time: datetime
    tier: HappyMomentTier
    name: str


class HappyMomentService:
    """
    Сервис управления "счастливыми мигами" - временными бонусными периодами.

    Функционал:
    - Генерация расписания на сутки (2 случайных времени)
    - Запуск/завершение мига
    - Проверка активного множителя
    - Отправка уведомлений во все группы
    """

    # Дефолтные тиры (если не заданы в конфиге)
    DEFAULT_TIERS = [
        HappyMomentTier(duration_minutes=1, multiplier=5.0),
        HappyMomentTier(duration_minutes=2, multiplier=4.0),
        HappyMomentTier(duration_minutes=3, multiplier=3.0),
        HappyMomentTier(duration_minutes=5, multiplier=2.5),
        HappyMomentTier(duration_minutes=10, multiplier=2.0),
        HappyMomentTier(duration_minutes=15, multiplier=1.5),
    ]

    def __init__(
        self,
        bot: Bot,
        db: Database,
        allowed_chat_ids: list[int],
        timezone_str: str = "Asia/Yekaterinburg",
        events_per_day: int = 2,
        active_hours_weight: int = 90,
        active_hours_start: str = "08:00",
        active_hours_end: str = "02:00",
        tiers: list[HappyMomentTier] | None = None,
        enabled: bool = True,
    ):
        self.bot = bot
        self.db = db
        self.allowed_chat_ids = allowed_chat_ids
        self.timezone = pytz.timezone(timezone_str)
        self.events_per_day = events_per_day
        self.active_hours_weight = active_hours_weight
        self.active_hours_start = self._parse_time(active_hours_start)
        self.active_hours_end = self._parse_time(active_hours_end)
        self.tiers = tiers or self.DEFAULT_TIERS
        self.enabled = enabled

        # Состояние
        self.schedule: list[ScheduledMoment] = []
        self.active_moment: ActiveMoment | None = None
        self._schedule_date: datetime | None = None  # Дата, на которую сгенерировано расписание

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """Парсит время в формате HH:MM"""
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    def _is_in_active_hours(self, dt: datetime) -> bool:
        """Проверяет, попадает ли время в активный период (08:00-02:00)"""
        hour = dt.hour
        start_h, _ = self.active_hours_start
        end_h, _ = self.active_hours_end

        # Период переходит через полночь (например, 08:00 - 02:00)
        if start_h > end_h:
            return hour >= start_h or hour < end_h
        else:
            return start_h <= hour < end_h

    def _generate_random_time(self, date: datetime, is_active_hours: bool) -> datetime:
        """Генерирует случайное время в указанный день"""
        start_h, start_m = self.active_hours_start
        end_h, end_m = self.active_hours_end

        if is_active_hours:
            # Активное время: 08:00-02:00
            if start_h > end_h:
                # Период через полночь
                # Первая часть: start_h:00 до 23:59
                # Вторая часть: 00:00 до end_h:00
                first_part_minutes = (24 - start_h) * 60 - start_m
                second_part_minutes = end_h * 60 + end_m
                total_minutes = first_part_minutes + second_part_minutes

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
                    # Если это после полуночи, это уже следующий день
                    # Но мы генерируем для конкретной даты, так что оставляем как есть
            else:
                # Обычный период в один день
                total_minutes = (end_h - start_h) * 60 + (end_m - start_m)
                random_minute = random.randint(0, total_minutes - 1)
                hour = start_h + (start_m + random_minute) // 60
                minute = (start_m + random_minute) % 60
        else:
            # Ночное время: 02:00-08:00
            night_start_h, night_start_m = end_h, end_m
            night_end_h, night_end_m = start_h, start_m

            total_minutes = (night_end_h - night_start_h) * 60 + (night_end_m - night_start_m)
            random_minute = random.randint(0, total_minutes - 1)
            hour = night_start_h + random_minute // 60
            minute = random_minute % 60

        return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def generate_daily_schedule(self) -> list[ScheduledMoment]:
        """
        Генерирует расписание на текущие сутки.
        Вызывается в 00:00 или при старте бота.
        """
        if not self.enabled:
            self.schedule = []
            return []

        now = datetime.now(self.timezone)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Если расписание уже сгенерировано на сегодня, не перегенерируем
        if self._schedule_date and self._schedule_date.date() == today.date():
            # Фильтруем только будущие события
            self.schedule = [m for m in self.schedule if m.scheduled_time > now]
            return self.schedule

        scheduled_times: list[datetime] = []
        moments: list[ScheduledMoment] = []

        for _ in range(self.events_per_day):
            # Решаем, активное или ночное время
            is_active = random.randint(1, 100) <= self.active_hours_weight

            # Генерируем время
            max_attempts = 100
            for _attempt in range(max_attempts):
                random_time = self._generate_random_time(today, is_active)

                # Если время уже прошло, пропускаем
                if random_time <= now:
                    continue

                # Проверяем, что не совпадает с другими (минимум 1 минута разницы)
                is_unique = all(
                    abs((random_time - t).total_seconds()) >= 60 for t in scheduled_times
                )

                if is_unique:
                    scheduled_times.append(random_time)
                    break
            else:
                # Не удалось найти уникальное время, пропускаем этот миг
                continue

            # Выбираем случайный тир
            tier = random.choice(self.tiers)

            # Выбираем случайное название
            name = random.choice(MOMENT_NAMES)

            moments.append(
                ScheduledMoment(
                    scheduled_time=random_time,
                    tier=tier,
                    name=name,
                )
            )

        # Сортируем по времени
        moments.sort(key=lambda m: m.scheduled_time)

        self.schedule = moments
        self._schedule_date = today

        logger.info(
            "Generated happy moment schedule",
            count=len(moments),
            times=[m.scheduled_time.strftime("%H:%M") for m in moments],
        )

        return moments

    async def start_moment(self, moment: ScheduledMoment):
        """Запускает счастливый миг"""
        if not self.enabled:
            return

        now = datetime.now(self.timezone)
        end_time = now + timedelta(minutes=moment.tier.duration_minutes)

        self.active_moment = ActiveMoment(
            start_time=now,
            end_time=end_time,
            tier=moment.tier,
            name=moment.name,
        )

        # Логируем событие старта
        event_id = str(uuid.uuid4())
        metadata = json.dumps(
            {
                "name": moment.name,
                "duration_minutes": moment.tier.duration_minutes,
                "multiplier": moment.tier.multiplier,
            }
        )
        await self.db.add_event(
            event_id, 0, "happy_moment_start", int(moment.tier.multiplier), metadata
        )

        logger.info(
            "Happy moment started",
            name=moment.name,
            duration=moment.tier.duration_minutes,
            multiplier=moment.tier.multiplier,
        )

        # Отправляем уведомления
        await self._send_start_notification(moment)

    async def end_moment(self):
        """Завершает текущий счастливый миг"""
        if self.active_moment:
            logger.info(
                "Happy moment ended",
                name=self.active_moment.name,
            )
            self.active_moment = None

    async def _send_start_notification(self, moment: ScheduledMoment):
        """Отправляет уведомление о старте во все группы"""
        duration = moment.tier.duration_minutes
        multiplier = moment.tier.multiplier

        # Форматируем множитель
        if multiplier == int(multiplier):
            mult_str = str(int(multiplier))
        else:
            mult_str = str(multiplier)

        # Форматируем длительность
        if duration == 1:
            duration_str = "1 минуту"
        elif duration in (2, 3, 4):
            duration_str = f"{duration} минуты"
        else:
            duration_str = f"{duration} минут"

        text = (
            f"🎰✨ <b>{moment.name}!</b> ✨🎰\n\n"
            f"Ближайшие {duration_str} все выигрыши в слотах умножаются на {mult_str}!\n\n"
            f"Крутите барабаны! 🍀"
        )

        for chat_id in self.allowed_chat_ids:
            try:
                await self.bot.send_message(chat_id, text)
            except Exception as e:
                logger.warning(
                    "Failed to send happy moment notification",
                    chat_id=chat_id,
                    error=str(e),
                )

    def get_active_multiplier(self) -> float | None:
        """
        Возвращает текущий множитель или None, если миг не активен.
        Также автоматически завершает истекший миг.
        """
        if not self.active_moment:
            return None

        now = datetime.now(self.timezone)

        if now >= self.active_moment.end_time:
            # Миг истёк
            self.active_moment = None
            return None

        return self.active_moment.tier.multiplier

    def get_active_moment_info(self) -> dict | None:
        """Возвращает информацию о текущем активном миге"""
        if not self.active_moment:
            return None

        now = datetime.now(self.timezone)

        if now >= self.active_moment.end_time:
            self.active_moment = None
            return None

        return {
            "name": self.active_moment.name,
            "multiplier": self.active_moment.tier.multiplier,
            "duration_minutes": self.active_moment.tier.duration_minutes,
            "remaining_seconds": (self.active_moment.end_time - now).total_seconds(),
        }

    def is_active(self) -> bool:
        """Проверяет, активен ли счастливый миг"""
        return self.get_active_multiplier() is not None

    def get_next_scheduled(self) -> ScheduledMoment | None:
        """Возвращает следующий запланированный миг"""
        now = datetime.now(self.timezone)

        for moment in self.schedule:
            if moment.scheduled_time > now:
                return moment

        return None
