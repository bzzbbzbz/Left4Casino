#!/usr/bin/env python3
"""
Скрипт для получения информации об активном ограблении банка.
Выводит pot_cap_pct и другие параметры.
"""

import asyncio
import json
from pathlib import Path

import aiosqlite


def format_number(n):
    """Форматирует число с разделителями тысяч"""
    if n is None:
        return "0"
    return f"{int(n):,}".replace(",", " ")


async def get_heist_info():
    """Получает информацию об активном ограблении из БД"""
    db_path = Path(__file__).parent / "telegram-casino-bot" / "bot" / "casino.db"

    # Получаем последний heist_start
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("""
            SELECT event_id, user_id, amount, metadata, created_at, chat_id
            FROM event_history
            WHERE event_type = 'heist_start'
            ORDER BY created_at DESC
            LIMIT 1
        """) as cursor:
            row = await cursor.fetchone()

            if not row:
                print("❌ Не найдено ни одного ограбления в истории")
                return None

            event_id, user_id, amount, metadata_str, created_at, chat_id = row
            metadata = json.loads(metadata_str) if metadata_str else {}

        # Проверяем, есть ли завершение этого ограбления
        async with db.execute(
            """
            SELECT COUNT(*) FROM event_history
            WHERE event_type IN ('heist_win', 'heist_no_winner')
            AND created_at > ?
            AND chat_id = ?
        """,
            (created_at, chat_id),
        ) as cursor:
            ended_count = (await cursor.fetchone())[0]
            is_active = ended_count == 0

        return {
            "event_id": event_id,
            "chat_id": chat_id,
            "created_at": created_at,
            "is_active": is_active,
            "metadata": metadata,
        }


async def get_heist_contributions(chat_id: str, start_time: str):
    """Получает все вклады в ограбление"""
    db_path = Path(__file__).parent / "telegram-casino-bot" / "bot" / "casino.db"

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT COUNT(*), SUM(ABS(amount))
            FROM event_history
            WHERE event_type = 'heist_contribution'
            AND chat_id = ?
            AND created_at >= ?
        """,
            (chat_id, start_time),
        ) as cursor:
            row = await cursor.fetchone()
            return {
                "total_spins": row[0] if row else 0,
                "total_contributed": row[1] if row and row[1] else 0,
            }


async def main():
    print("🔍 Поиск информации об ограблении банка...\n")

    # Дефолтные значения из конфига
    min_pot_pct = 10
    commission_pct = 30
    max_duration_minutes = 30

    # Получаем информацию об ограблении
    heist_info = await get_heist_info()

    if not heist_info:
        return

    metadata = heist_info["metadata"]

    # Извлекаем данные
    base_value = metadata.get("base_value", 0)
    pot_cap = metadata.get("pot_cap", 0)
    seed_pct = metadata.get("seed_pct", 0)
    phase1_duration = metadata.get("phase1_duration_minutes", 0)
    phase2_duration = metadata.get("phase2_duration_minutes", 0)

    # Вычисляем pot_cap_pct
    pot_cap_pct = (pot_cap / base_value * 100) if base_value > 0 else 0

    # Получаем вклады
    contributions = await get_heist_contributions(heist_info["chat_id"], heist_info["created_at"])

    # Статус
    status = "🟢 АКТИВНО" if heist_info["is_active"] else "🔴 ЗАВЕРШЕНО"

    # Вывод информации
    print("=" * 60)
    print(f"🏦 ОГРАБЛЕНИЕ БАНКА — {status}")
    print("=" * 60)
    print(f"📅 Время старта: {heist_info['created_at']}")
    print(f"💬 Chat ID: {heist_info['chat_id']}")
    print(f"🆔 Event ID: {heist_info['event_id']}")
    print()

    print("📊 ЭКОНОМИЧЕСКИЕ ПАРАМЕТРЫ:")
    print("-" * 60)
    print(f"  B (базовая величина):     {format_number(base_value)} очков")
    print(f"  pot_cap:                  {format_number(pot_cap)} очков")
    print(f"  pot_cap_pct:              {pot_cap_pct:.1f}%")
    print(f"  seed_pct:                 {seed_pct}%")
    print(f"  min_pot_pct (из конфига): {min_pot_pct}%")
    print(f"  commission_pct:           {commission_pct}%")
    print()

    print("⏱️  ДЛИТЕЛЬНОСТЬ ФАЗ:")
    print("-" * 60)
    print(f"  Фаза 1 (Ограбление):      {phase1_duration} мин")
    print(f"  Фаза 2 (Тревога):         {phase2_duration} мин")
    print(f"  Максимум (hard cap):      {max_duration_minutes} мин")
    print()

    if heist_info["is_active"]:
        print("📈 ТЕКУЩАЯ СТАТИСТИКА:")
        print("-" * 60)
        print(f"  Всего спинов:             {contributions['total_spins']}")
        print(
            f"  Всего внесено:            {format_number(contributions['total_contributed'])} очков"
        )
        print()

    print("🔢 ФОРМУЛА РАСЧЁТА:")
    print("-" * 60)
    print("  pot_cap_pct = (pot_cap / base_value) × 100")
    print(f"  pot_cap_pct = ({format_number(pot_cap)} / {format_number(base_value)}) × 100")
    print(f"  pot_cap_pct = {pot_cap_pct:.2f}%")
    print()

    print("💡 ПОРОГОВЫЕ ЗНАЧЕНИЯ:")
    print("-" * 60)
    min_pot = int(base_value * min_pot_pct / 100)
    max_payout = int(pot_cap * (100 - commission_pct) / 100)
    print(f"  min_pot ({min_pot_pct}% от B):        {format_number(min_pot)} очков")
    print(f"  Макс. выплата (70% от pot_cap): {format_number(max_payout)} очков")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
