# [START SPEC:TASK-010:user-repository]
"""User repository for user-related database operations."""

from __future__ import annotations

import aiosqlite

from bot.models.entities import User
from bot.money import decode_money, encode_money, normalize_money_dict
from bot.repositories.base import BaseRepository

USER_MONEY_FIELDS = ("balance", "bid", "safe_balance", "last_dice_bet", "total_won", "total_lost")


class UserRepository(BaseRepository[User]):
    """Repository for user operations."""

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by ID."""
        row = await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        d = normalize_money_dict(dict(row), USER_MONEY_FIELDS)
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
            return decode_money(row["balance"])
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (user_id, balance, bid) VALUES (?, ?, '1')",
                (user_id, encode_money(default_balance)),
            )
            await db.commit()
        return default_balance

    async def update_balance(self, user_id: int, amount: int) -> None:
        """Update user balance (add amount)."""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("BEGIN IMMEDIATE")
                async with db.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cur:
                    row = await cur.fetchone()
                current = decode_money(row[0]) if row else 0
                await db.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (encode_money(current + amount), user_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def set_balance(self, user_id: int, new_balance: int) -> None:
        """Set user balance to new value."""
        await self._execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (encode_money(new_balance), user_id),
        )

    async def get_bid(self, user_id: int) -> int:
        """Get user bid."""
        row = await self._fetchone("SELECT bid FROM users WHERE user_id = ?", (user_id,))
        return decode_money(row["bid"], default=1) if row and row["bid"] is not None else 1

    async def update_bid(self, user_id: int, new_bid: int) -> None:
        """Update user bid."""
        await self._execute(
            "UPDATE users SET bid = ? WHERE user_id = ?",
            (encode_money(new_bid), user_id),
        )

    async def get_user_by_nickname(self, nickname: str) -> dict | None:
        """Get user dict by nickname (for handlers that need dict)."""
        clean = nickname.lstrip("@")
        row = await self._fetchone(
            "SELECT * FROM users WHERE nickname = ? COLLATE NOCASE",
            (clean,),
        )
        return normalize_money_dict(dict(row), USER_MONEY_FIELDS) if row else None

    async def register_user(self, user_id: int, nickname: str) -> None:
        """Insert or update user (nickname)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, nickname, balance, bid) VALUES (?, ?, '50', '1')",
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                await db.execute("BEGIN IMMEDIATE")
                won_add = amount if amount > 0 else 0
                lost_add = abs(amount) if amount < 0 else 0
                bankruptcy_add = 1 if is_bankruptcy else 0
                async with db.execute(
                    "SELECT total_won, total_lost FROM users WHERE user_id = ?", (user_id,)
                ) as cur:
                    row = await cur.fetchone()
                current_won = decode_money(row["total_won"]) if row else 0
                current_lost = decode_money(row["total_lost"]) if row else 0
                await db.execute(
                    """UPDATE users
                       SET games_played = games_played + 1,
                           total_won = ?,
                           total_lost = ?,
                           bankruptcy_count = bankruptcy_count + ?
                       WHERE user_id = ?""",
                    (
                        encode_money(current_won + won_add),
                        encode_money(current_lost + lost_add),
                        bankruptcy_add,
                        user_id,
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

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
            try:
                await db.execute("BEGIN IMMEDIATE")
                async with db.execute(
                    "SELECT balance FROM users WHERE user_id = ?",
                    (from_user_id,),
                ) as cur:
                    row = await cur.fetchone()
                sender_balance = decode_money(row[0]) if row else 0
                if row is None or sender_balance < amount:
                    await db.rollback()
                    return False
                async with db.execute(
                    "SELECT balance FROM users WHERE user_id = ?", (to_user_id,)
                ) as cur:
                    receiver_row = await cur.fetchone()
                receiver_balance = decode_money(receiver_row[0]) if receiver_row else 0
                await db.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (encode_money(sender_balance - amount), from_user_id),
                )
                await db.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (encode_money(receiver_balance + amount), to_user_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return True

    async def get_safe_balance(self, user_id: int) -> int:
        """Get user safe balance."""
        row = await self._fetchone(
            "SELECT safe_balance FROM users WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return 0
        return decode_money(row["safe_balance"]) if row["safe_balance"] is not None else 0

    # [START SPEC:SAFE-ATOMIC:safe_deposit]
    # REQ: Атомарно balance -= amount, safe_balance += amount (в одной транзакции)
    # Source: SAFE_SPEC.md, сейф
    # CRITICAL: Два UPDATE в одном контексте; не разрывать
    async def safe_deposit(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]:
        """Deposit to safe (balance -> safe_balance). Returns (True, new_balance, new_safe) or (False, error)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                await db.execute("BEGIN IMMEDIATE")
                async with db.execute(
                    "SELECT balance, safe_balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    await db.rollback()
                    return (False, "Пользователь не найден")
                balance = decode_money(row["balance"])
                safe_balance = decode_money(row["safe_balance"])
                if balance < amount:
                    await db.rollback()
                    return (False, "Недостаточно средств на балансе")
                await db.execute(
                    """UPDATE users
                       SET balance = ?,
                           safe_balance = ?
                       WHERE user_id = ?""",
                    (encode_money(balance - amount), encode_money(safe_balance + amount), user_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return (True, balance - amount, safe_balance + amount)

    # [END SPEC:SAFE-ATOMIC]

    # [START SPEC:SAFE-ATOMIC:safe_withdraw]
    # REQ: Атомарно safe_balance -= amount, balance += amount (в одной транзакции)
    # Source: SAFE_SPEC.md, сейф
    # CRITICAL: Два UPDATE в одном контексте; не разрывать
    async def safe_withdraw(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]:
        """Withdraw from safe (safe_balance -> balance). Returns (True, new_balance, new_safe) or (False, error)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                await db.execute("BEGIN IMMEDIATE")
                async with db.execute(
                    "SELECT balance, safe_balance FROM users WHERE user_id = ?",
                    (user_id,),
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    await db.rollback()
                    return (False, "Пользователь не найден")
                balance = decode_money(row["balance"])
                safe_balance = decode_money(row["safe_balance"])
                if safe_balance < amount:
                    await db.rollback()
                    return (False, "Недостаточно средств в сейфе")
                await db.execute(
                    """UPDATE users
                       SET safe_balance = ?,
                           balance = ?
                       WHERE user_id = ?""",
                    (encode_money(safe_balance - amount), encode_money(balance + amount), user_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return (True, balance + amount, safe_balance - amount)

    # [END SPEC:SAFE-ATOMIC]


# [END SPEC:TASK-010:user-repository]
