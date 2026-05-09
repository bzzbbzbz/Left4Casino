#!/usr/bin/env python3
"""
Скрипт для просмотра ближайших запланированных ивентов (Happy Moment + Heist).
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiosqlite
import pytz


def format_remaining(seconds: float) -> str:
    """Format seconds as compact remaining time."""
    if seconds <= 0:
        return "0s"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_event_type(event_type: str) -> str:
    mapping = {
        "happy_moment_start": "🎰 Happy Moment",
        "heist_warning": "⏰ Heist Warning",
        "heist_start": "🏦 Heist Start",
    }
    return mapping.get(event_type, event_type)


async def get_scheduled_events(limit: int, all_days: bool):
    db_path = Path(__file__).parent / "bot" / "casino.db"

    timezone = pytz.timezone("Asia/Yekaterinburg")
    now = datetime.now(timezone)
    today = now.date().isoformat()

    query = """
        SELECT event_id, event_type, chat_id, scheduled_at, timezone, source_date, status, metadata
        FROM scheduled_events
        WHERE event_type IN ('happy_moment_start', 'heist_warning', 'heist_start')
          AND status IN ('scheduled', 'running', 'done')
    """
    params: list[object] = []

    if not all_days:
        query += " AND source_date = ?"
        params.append(today)

    query += " ORDER BY scheduled_at ASC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        try:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows], now, today
        except aiosqlite.OperationalError as exc:
            if "no such table: scheduled_events" in str(exc):
                print("❌ Таблица scheduled_events не найдена.")
                print("Запустите бота один раз или примените миграции:")
                print("  python migrations/migration_runner.py")
                return [], now, today
            raise


def print_events(events: list[dict], now: datetime, today: str):
    if not events:
        print("❌ Запланированные ивенты не найдены")
        return

    print("=" * 90)
    print("📅 РАСПИСАНИЕ БЛИЖАЙШИХ ИВЕНТОВ")
    print("=" * 90)
    print(f"🕒 Сейчас: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"📆 Текущий день: {today}")
    print()

    for idx, row in enumerate(events, start=1):
        scheduled_at = datetime.fromisoformat(row["scheduled_at"])
        delta = (scheduled_at - now).total_seconds()
        status = row["status"]
        remaining = format_remaining(delta) if status == "scheduled" else "-"
        kind = format_event_type(row["event_type"])

        extra = ""
        if row["event_type"] == "happy_moment_start" and row.get("metadata"):
            metadata = json.loads(row["metadata"])
            mult = metadata.get("multiplier")
            duration = metadata.get("duration_minutes")
            name = metadata.get("name")
            extra = f"{name} | x{mult} | {duration} min"

        print(f"{idx:02d}. {kind}")
        print(f"    ID:         {row['event_id']}")
        print(f"    Source day: {row['source_date']}")
        print(f"    Time:       {scheduled_at.strftime('%Y-%m-%d %H:%M:%S %z')}")
        print(f"    Status:     {status}")
        print(f"    Starts in:  {remaining}")
        if row.get("chat_id") is not None:
            print(f"    Chat ID:    {row['chat_id']}")
        if extra:
            print(f"    Details:    {extra}")
        print()

    print("=" * 90)


async def main():
    parser = argparse.ArgumentParser(
        description="Показать расписание будущих ивентов happy moment/heist"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Максимум строк в выводе (по умолчанию: 20)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Показывать события не только за сегодня",
    )
    args = parser.parse_args()

    events, now, today = await get_scheduled_events(limit=args.limit, all_days=args.all)
    print_events(events, now, today)


if __name__ == "__main__":
    asyncio.run(main())
