# [START SPEC:TASK-010:event-repository]
"""Event repository for event history operations."""

import json
from datetime import datetime
from typing import Any

import aiosqlite

from bot.models.events import GameEvent, create_event
from bot.money import decode_money, encode_money
from bot.repositories.base import BaseRepository


class EventRepository(BaseRepository[GameEvent]):
    """Repository for event history."""

    async def add(self, event: GameEvent) -> None:
        """Add event from model."""
        metadata_str = json.dumps(event.metadata) if event.metadata else None
        created = event.created_at.isoformat() if event.created_at else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO event_history
                   (event_id, user_id, event_type, amount, created_at, chat_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.user_id,
                    event.event_type,
                    encode_money(event.amount),
                    created,
                    event.chat_id,
                    metadata_str,
                ),
            )
            await db.commit()

    async def add_event(
        self,
        event_id: str,
        user_id: int,
        event_type: str,
        amount: int,
        metadata: str | None = None,
        chat_id: int | None = None,
    ) -> None:
        """Add event (raw)."""
        await self._execute(
            """INSERT INTO event_history
               (event_id, user_id, event_type, amount, metadata, chat_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, event_type, encode_money(amount), metadata, chat_id),
        )

    async def get_user_events(
        self,
        user_id: int,
        limit: int = 100,
    ) -> list[GameEvent]:
        """Get recent events for user."""
        rows = await self._fetchall(
            """SELECT * FROM event_history
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        )
        return [self._row_to_event(dict(row)) for row in rows]

    def _row_to_event(self, row: dict[str, Any]) -> GameEvent:
        """Convert DB row to GameEvent."""
        meta = row.get("metadata")
        if isinstance(meta, str) and meta:
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        else:
            meta = {}
        created = row.get("created_at")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created = datetime.now()
        return create_event(
            event_type=row["event_type"],
            event_id=row["event_id"],
            user_id=row["user_id"],
            amount=decode_money(row["amount"]),
            chat_id=row.get("chat_id"),
            metadata=meta,
            created_at=created,
        )

    async def get_last_credit_event(self, user_id: int) -> dict[str, Any] | None:
        """Get last credit_grant event for user."""
        row = await self._fetchone(
            """SELECT created_at FROM event_history
               WHERE user_id = ? AND event_type = 'credit_grant'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        )
        return dict(row) if row else None


# [END SPEC:TASK-010:event-repository]
