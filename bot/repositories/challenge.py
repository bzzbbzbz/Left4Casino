# [START SPEC:TASK-010:challenge-repository]
"""Dice challenge repository for PvP duels."""

from typing import Any

import aiosqlite

from bot.repositories.base import BaseRepository


class ChallengeRepository(BaseRepository[Any]):
    """Repository for dice challenges."""

    async def create_dice_challenge(
        self,
        challenge_id: str,
        chat_id: int,
        initiator_id: int,
        nickname: str | None,
        first_name: str | None,
        bet: int,
        going_debt: bool,
        message_id: int,
    ) -> None:
        """Create a new dice challenge."""
        await self._execute(
            """INSERT INTO dice_challenges
               (challenge_id, chat_id, initiator_id, initiator_nickname, initiator_first_name,
                bet_amount, initiator_going_debt, status, message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                challenge_id,
                chat_id,
                initiator_id,
                nickname,
                first_name,
                bet,
                1 if going_debt else 0,
                message_id,
            ),
        )

    def _row_to_challenge(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert DB row to challenge dict."""
        d = dict(row)
        return {
            "challenge_id": d["challenge_id"],
            "chat_id": d["chat_id"],
            "initiator_id": d["initiator_id"],
            "initiator_nickname": d.get("initiator_nickname"),
            "initiator_first_name": d.get("initiator_first_name"),
            "opponent_id": d.get("opponent_id"),
            "opponent_nickname": d.get("opponent_nickname"),
            "opponent_first_name": d.get("opponent_first_name"),
            "bet_amount": d["bet_amount"],
            "initiator_going_debt": d.get("initiator_going_debt"),
            "status": d.get("status", "pending"),
            "initiator_roll": d.get("initiator_roll"),
            "opponent_roll": d.get("opponent_roll"),
            "winner_id": d.get("winner_id"),
            "message_id": d.get("message_id"),
            "created_at": d.get("created_at"),
            "accepted_at": d.get("accepted_at"),
            "completed_at": d.get("completed_at"),
        }

    async def get_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        """Get challenge by id."""
        row = await self._fetchone(
            "SELECT * FROM dice_challenges WHERE challenge_id = ?",
            (challenge_id,),
        )
        return self._row_to_challenge(row) if row else None

    async def get_active_challenge_by_user(
        self, user_id: int, chat_id: int
    ) -> dict[str, Any] | None:
        """Get active (pending/accepted/rolling) challenge for user in chat."""
        row = await self._fetchone(
            """SELECT * FROM dice_challenges
               WHERE (initiator_id = ? OR opponent_id = ?)
                 AND chat_id = ?
                 AND status IN ('pending', 'accepted', 'rolling')
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, user_id, chat_id),
        )
        return self._row_to_challenge(row) if row else None

    async def get_accepted_challenge_for_user(
        self, user_id: int, chat_id: int
    ) -> dict[str, Any] | None:
        """Get accepted/rolling challenge where user is participant."""
        row = await self._fetchone(
            """SELECT * FROM dice_challenges
               WHERE (initiator_id = ? OR opponent_id = ?)
                 AND chat_id = ?
                 AND status IN ('accepted', 'rolling')
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, user_id, chat_id),
        )
        return self._row_to_challenge(row) if row else None

    async def accept_challenge(
        self,
        challenge_id: str,
        opponent_id: int,
        opponent_nickname: str | None,
        opponent_first_name: str | None,
    ) -> bool:
        """Set opponent and status to accepted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """UPDATE dice_challenges
                   SET opponent_id = ?, opponent_nickname = ?, opponent_first_name = ?,
                       status = 'accepted', accepted_at = CURRENT_TIMESTAMP
                   WHERE challenge_id = ? AND status = 'pending'""",
                (opponent_id, opponent_nickname, opponent_first_name, challenge_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def record_roll(self, challenge_id: str, user_id: int, roll_value: int) -> None:
        """Record roll for initiator or opponent; set status to rolling if first roll."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT initiator_id, opponent_id FROM dice_challenges WHERE challenge_id = ?",
                (challenge_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return
            initiator_id, opponent_id = row[0], row[1]
            if user_id == initiator_id:
                await db.execute(
                    "UPDATE dice_challenges SET initiator_roll = ?, status = 'rolling' WHERE challenge_id = ?",
                    (roll_value, challenge_id),
                )
            elif user_id == opponent_id:
                await db.execute(
                    "UPDATE dice_challenges SET opponent_roll = ? WHERE challenge_id = ?",
                    (roll_value, challenge_id),
                )
            await db.commit()

    async def complete_challenge(self, challenge_id: str, winner_id: int | None) -> None:
        """Mark challenge completed and set winner_id."""
        await self._execute(
            """UPDATE dice_challenges
               SET status = 'completed', winner_id = ?, completed_at = CURRENT_TIMESTAMP
               WHERE challenge_id = ?""",
            (winner_id, challenge_id),
        )

    async def cancel_challenge(self, challenge_id: str) -> None:
        """Cancel challenge."""
        await self._execute(
            "UPDATE dice_challenges SET status = 'cancelled' WHERE challenge_id = ?",
            (challenge_id,),
        )

    async def get_last_dice_bet(self, user_id: int) -> int | None:
        """Get last bet amount for user (stored in users.last_dice_bet)."""
        row = await self._fetchone(
            "SELECT last_dice_bet FROM users WHERE user_id = ?",
            (user_id,),
        )
        if row is None or row["last_dice_bet"] is None:
            return None
        return int(row["last_dice_bet"])

    async def set_last_dice_bet(self, user_id: int, bet: int) -> None:
        """Store last dice bet for user (caller must ensure user exists, e.g. register_user)."""
        await self._execute(
            "UPDATE users SET last_dice_bet = ? WHERE user_id = ?",
            (bet, user_id),
        )


# [END SPEC:TASK-010:challenge-repository]
