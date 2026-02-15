# [START SPEC:TASK-010:user-repository]
"""User repository for user-related database operations."""

from __future__ import annotations

import aiosqlite

from bot.models.entities import User
from bot.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for user operations."""

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by ID."""
        row = await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        d = dict(row)
        return User(
            user_id=d["user_id"],
            nickname=d.get("nickname"),
            balance=d.get("balance", 50),
            bid=d.get("bid", 1),
            state=d.get("state", "IDLE"),
            created_at=d.get("created_at"),
            games_played=d.get("games_played", 0),
            total_won=d.get("total_won", 0),
            total_lost=d.get("total_lost", 0),
            bankruptcy_count=d.get("bankruptcy_count", 0),
            safe_balance=d.get("safe_balance", 0),
        )

    async def get_balance(self, user_id: int, default_balance: int = 0) -> int:
        """Get user balance; create user with default_balance if not exists."""
        row = await self._fetchone(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,),
        )
        if row is not None:
            return row["balance"]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (user_id, balance, bid) VALUES (?, ?, 1)",
                (user_id, default_balance),
            )
            await db.commit()
        return default_balance

    async def update_balance(self, user_id: int, amount: int) -> None:
        """Update user balance (add amount)."""
        await self._execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id),
        )

    async def set_balance(self, user_id: int, new_balance: int) -> None:
        """Set user balance to new value."""
        await self._execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id),
        )

    async def get_bid(self, user_id: int) -> int:
        """Get user bid."""
        row = await self._fetchone("SELECT bid FROM users WHERE user_id = ?", (user_id,))
        return row["bid"] if row and row["bid"] is not None else 1

    async def update_bid(self, user_id: int, new_bid: int) -> None:
        """Update user bid."""
        await self._execute(
            "UPDATE users SET bid = ? WHERE user_id = ?",
            (new_bid, user_id),
        )

    async def get_user_by_nickname(self, nickname: str) -> dict | None:
        """Get user dict by nickname (for handlers that need dict)."""
        clean = nickname.lstrip("@")
        row = await self._fetchone(
            "SELECT * FROM users WHERE nickname = ? COLLATE NOCASE",
            (clean,),
        )
        return dict(row) if row else None

    async def register_user(self, user_id: int, nickname: str) -> None:
        """Insert or update user (nickname)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, nickname, balance, bid) VALUES (?, ?, 50, 1)",
                (user_id, nickname),
            )
            await db.execute(
                "UPDATE users SET nickname = ? WHERE user_id = ?",
                (nickname, user_id),
            )
            await db.commit()

    async def update_user_state(self, user_id: int, state: str) -> None:
        """Update user FSM state."""
        await self._execute(
            "UPDATE users SET state = ? WHERE user_id = ?",
            (state, user_id),
        )

    async def update_user_stats(
        self, user_id: int, amount: int, is_bankruptcy: bool = False
    ) -> None:
        """Update games_played, total_won, total_lost, bankruptcy_count."""
        won_add = amount if amount > 0 else 0
        lost_add = abs(amount) if amount < 0 else 0
        bankruptcy_add = 1 if is_bankruptcy else 0
        await self._execute(
            """UPDATE users
               SET games_played = games_played + 1,
                   total_won = total_won + ?,
                   total_lost = total_lost + ?,
                   bankruptcy_count = bankruptcy_count + ?
               WHERE user_id = ?""",
            (won_add, lost_add, bankruptcy_add, user_id),
        )

    async def increment_bankruptcy_count(self, user_id: int) -> None:
        """Increment user's bankruptcy_count by 1."""
        await self._execute(
            "UPDATE users SET bankruptcy_count = bankruptcy_count + 1 WHERE user_id = ?",
            (user_id,),
        )

    async def transfer(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
    ) -> bool:
        """Atomic balance transfer. Returns False if insufficient balance."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (from_user_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None or row[0] < amount:
                return False
            await db.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, from_user_id),
            )
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, to_user_id),
            )
            await db.commit()
        return True

    async def get_safe_balance(self, user_id: int) -> int:
        """Get user safe balance."""
        row = await self._fetchone(
            "SELECT safe_balance FROM users WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return 0
        return row["safe_balance"] if row["safe_balance"] is not None else 0

    async def safe_deposit(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]:
        """Deposit to safe (balance -> safe_balance). Returns (True, new_balance, new_safe) or (False, error)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT balance, safe_balance FROM users WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return (False, "Пользователь не найден")
            balance = row["balance"] or 0
            safe_balance = row["safe_balance"] or 0
            if balance < amount:
                return (False, "Недостаточно средств на балансе")
            await db.execute(
                """UPDATE users
                   SET balance = balance - ?,
                       safe_balance = safe_balance + ?
                   WHERE user_id = ?""",
                (amount, amount, user_id),
            )
            await db.commit()
        return (True, balance - amount, safe_balance + amount)

    async def safe_withdraw(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]:
        """Withdraw from safe (safe_balance -> balance). Returns (True, new_balance, new_safe) or (False, error)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT balance, safe_balance FROM users WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return (False, "Пользователь не найден")
            balance = row["balance"] or 0
            safe_balance = row["safe_balance"] or 0
            if safe_balance < amount:
                return (False, "Недостаточно средств в сейфе")
            await db.execute(
                """UPDATE users
                   SET safe_balance = safe_balance - ?,
                       balance = balance + ?
                   WHERE user_id = ?""",
                (amount, amount, user_id),
            )
            await db.commit()
        return (True, balance + amount, safe_balance - amount)


# [END SPEC:TASK-010:user-repository]
