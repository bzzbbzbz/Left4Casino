# [START SPEC:TASK-010:debt-repository]
"""Debt repository for player debts (PvP)."""

import uuid
from typing import Any

import aiosqlite

from bot.repositories.base import BaseRepository


class DebtRepository(BaseRepository[Any]):
    """Repository for player_debts."""

    async def get_debt(
        self, chat_id: int, debtor_id: int, creditor_id: int
    ) -> dict[str, Any] | None:
        """Get debt row (debtor owes creditor) in chat."""
        row = await self._fetchone(
            """SELECT * FROM player_debts
               WHERE chat_id = ? AND debtor_id = ? AND creditor_id = ?""",
            (chat_id, debtor_id, creditor_id),
        )
        return dict(row) if row else None

    async def get_total_debt(self, user_id: int, chat_id: int) -> int:
        """Total amount user owes to others in this chat."""
        row = await self._fetchone(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM player_debts
               WHERE chat_id = ? AND debtor_id = ?""",
            (chat_id, user_id),
        )
        return int(row["total"]) if row and row["total"] is not None else 0

    async def create_or_update_debt(
        self,
        debtor_id: int,
        creditor_id: int,
        amount: int,
        chat_id: int,
        challenge_id: str,
    ) -> None:
        """Add debt (or increase existing). Optionally net with reverse debt."""
        async with aiosqlite.connect(self.db_path) as db:
            # [START SPEC:DEBT-SETTLEMENT:MutualOffset]
            # REQ: Если A должен B и B должен A — долги взаимно сокращаются (взаимозачёт)
            # Source: DICE_FIGHT_SPEC.md, "Взаимозачёт долгов"
            # CRITICAL: Логика net влияет на лимиты ставок и корректность долгов
            async with db.execute(
                """SELECT debt_id, amount FROM player_debts
                   WHERE chat_id = ? AND debtor_id = ? AND creditor_id = ?""",
                (chat_id, creditor_id, debtor_id),
            ) as cur:
                reverse = await cur.fetchone()
            if reverse:
                rev_id, rev_amount = reverse[0], reverse[1]
                # Net: reduce reverse by amount, or delete; reduce new debt
                if amount >= rev_amount:
                    await db.execute(
                        "DELETE FROM player_debts WHERE debt_id = ?",
                        (rev_id,),
                    )
                    amount -= rev_amount
                    if amount <= 0:
                        await db.commit()
                        return
                else:
                    await db.execute(
                        "UPDATE player_debts SET amount = amount - ?, updated_at = CURRENT_TIMESTAMP WHERE debt_id = ?",
                        (amount, rev_id),
                    )
                    await db.commit()
                    return
            # [END SPEC:DEBT-SETTLEMENT]
            # Existing debt (debtor owes creditor)?
            async with db.execute(
                """SELECT debt_id, amount FROM player_debts
                   WHERE chat_id = ? AND debtor_id = ? AND creditor_id = ?""",
                (chat_id, debtor_id, creditor_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing:
                await db.execute(
                    "UPDATE player_debts SET amount = amount + ?, updated_at = CURRENT_TIMESTAMP WHERE debt_id = ?",
                    (amount, existing[0]),
                )
            else:
                await db.execute(
                    """INSERT INTO player_debts (debt_id, chat_id, debtor_id, creditor_id, amount, challenge_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), chat_id, debtor_id, creditor_id, amount, challenge_id),
                )
            await db.commit()

    async def collect_debt(
        self, creditor_id: int, debtor_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]:
        """
        Collect debt: transfer up to min(amount, debt, debtor_balance) from debtor to creditor.
        Returns (True, actual_collected, remaining_debt) or (False, error_msg).
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (debtor_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return (False, "Должник не найден")
            debtor_balance = row["balance"] or 0
            async with db.execute(
                """SELECT debt_id, amount FROM player_debts
                   WHERE chat_id = ? AND debtor_id = ? AND creditor_id = ?""",
                (chat_id, debtor_id, creditor_id),
            ) as cur:
                debt_row = await cur.fetchone()
            if not debt_row or debt_row["amount"] <= 0:
                return (False, "Нет долга")
            debt_amount = debt_row["amount"]
            actual = min(amount, debt_amount, debtor_balance)
            if actual <= 0:
                return (False, "У должника нет средств")
            try:
                await db.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                    (actual, debtor_id),
                )
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (actual, creditor_id),
                )
                await db.execute(
                    """UPDATE player_debts
                       SET amount = amount - ?, updated_at = CURRENT_TIMESTAMP
                       WHERE debt_id = ?""",
                    (actual, debt_row["debt_id"]),
                )
                await db.execute("DELETE FROM player_debts WHERE amount <= 0")
                await db.commit()
            except Exception:
                await db.rollback()
                return (False, "Ошибка транзакции")
            remaining = debt_amount - actual
        return (True, actual, remaining)


# [END SPEC:TASK-010:debt-repository]
