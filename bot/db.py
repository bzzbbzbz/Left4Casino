import json
from pathlib import Path

import aiosqlite

from bot.models.entities import User
from bot.models.events import GameEvent
from bot.utils.context import add_db_action


class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            self.db_path = str(Path(__file__).parent / "casino.db")
        else:
            self.db_path = db_path

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    nickname TEXT,
                    balance INTEGER NOT NULL DEFAULT 50,
                    bid INTEGER DEFAULT 1,
                    state TEXT DEFAULT 'IDLE',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Event history table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_history (
                    event_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    event_type TEXT NOT NULL,
                    amount INTEGER DEFAULT 0,
                    metadata TEXT, -- JSON storage
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)

            # 3. AI Credit Sessions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ai_credit_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    status TEXT DEFAULT 'active', -- active, completed, rejected
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    finished_at DATETIME,
                    ai_score INTEGER,
                    reward_amount INTEGER,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)

            # 4. AI Dialogue Messages
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ai_dialogue_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT NOT NULL, -- user, assistant
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES ai_credit_sessions(session_id)
                )
            """)

            # 5. User Groups (for local leaderboards)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_groups (
                    user_id INTEGER,
                    chat_id INTEGER,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, chat_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)

            # Attempt to migrate existing users table (add new columns if missing)
            # This is a basic migration strategy for development
            try:
                await db.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN bid INTEGER DEFAULT 1")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN state TEXT DEFAULT 'IDLE'")
            except Exception:
                pass
            try:
                await db.execute(
                    "ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                )
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN games_played INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN total_won INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN total_lost INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN bankruptcy_count INTEGER DEFAULT 0")
            except Exception:
                pass

            # Add chat_id to event_history
            try:
                await db.execute("ALTER TABLE event_history ADD COLUMN chat_id INTEGER")
            except Exception:
                pass
            # Safe balance and last_dice_bet (for repositories)
            try:
                await db.execute("ALTER TABLE users ADD COLUMN safe_balance INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE users ADD COLUMN last_dice_bet INTEGER")
            except Exception:
                pass

            # dice_challenges (PvP duels)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dice_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    initiator_id INTEGER NOT NULL,
                    initiator_nickname TEXT,
                    initiator_first_name TEXT,
                    opponent_id INTEGER,
                    opponent_nickname TEXT,
                    opponent_first_name TEXT,
                    bet_amount INTEGER NOT NULL,
                    initiator_going_debt INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    initiator_roll INTEGER,
                    opponent_roll INTEGER,
                    winner_id INTEGER,
                    message_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    accepted_at DATETIME,
                    completed_at DATETIME,
                    FOREIGN KEY(initiator_id) REFERENCES users(user_id),
                    FOREIGN KEY(opponent_id) REFERENCES users(user_id)
                )
            """)
            # player_debts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS player_debts (
                    debt_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    debtor_id INTEGER NOT NULL,
                    creditor_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    challenge_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, debtor_id, creditor_id),
                    FOREIGN KEY(debtor_id) REFERENCES users(user_id),
                    FOREIGN KEY(creditor_id) REFERENCES users(user_id)
                )
            """)

            await db.commit()

    async def run_stats_backfill(self):
        """
        One-time migration script to populate stats from event_history.
        To disable this script, simply do not call it or comment out the call site.
        """
        print("Running stats backfill...")
        async with aiosqlite.connect(self.db_path) as db:
            # Get all unique users from event_history
            async with db.execute("SELECT DISTINCT user_id FROM event_history") as cursor:
                users = await cursor.fetchall()

            for (user_id,) in users:
                if user_id is None:
                    continue

                # Calculate stats
                async with db.execute(
                    """
                    SELECT
                        COUNT(*) as games,
                        SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as won,
                        SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as lost
                    FROM event_history
                    WHERE user_id = ? AND event_type IN ('win', 'loss')
                """,
                    (user_id,),
                ) as stats_cursor:
                    row = await stats_cursor.fetchone()
                    if row:
                        games, won, lost = row
                        games = games or 0
                        won = won or 0
                        lost = lost or 0

                        await db.execute(
                            """
                            UPDATE users
                            SET games_played = ?,
                                total_won = ?,
                                total_lost = ?
                            WHERE user_id = ?
                        """,
                            (games, won, lost, user_id),
                        )

            await db.commit()
        print("Stats backfill completed.")

    async def run_bankruptcy_backfill(self):
        """
        One-time migration script to calculate bankruptcy counts from event history.
        Also inserts missing bankruptcy events into event_history.
        """
        print("Running bankruptcy backfill...")
        async with aiosqlite.connect(self.db_path) as db:
            # Get all distinct users from event_history
            async with db.execute("SELECT DISTINCT user_id FROM event_history") as cursor:
                users = await cursor.fetchall()

            for (user_id,) in users:
                if user_id is None:
                    continue

                # Get all events for user ordered by time
                async with db.execute(
                    "SELECT event_type, amount, created_at FROM event_history WHERE user_id = ? ORDER BY created_at ASC",
                    (user_id,),
                ) as event_cursor:
                    events = await event_cursor.fetchall()

                # Filter out existing bankruptcy events to avoid duplicates, but keep them for checking
                existing_bankruptcy_timestamps = {
                    row[2] for row in events if row[0] == "bankruptcy"
                }

                # Replay balance
                balance = 50
                bk_count = 0
                was_bankrupt = False

                # We need to iterate non-bankruptcy events to calculate balance,
                # but we also need to know if a bankruptcy event ALREADY exists for a bankruptcy moment.
                # Since we can't easily match "moment" to "event" without complex logic,
                # we will rely on a heuristic: if we detect bankruptcy, and there is no 'bankruptcy' event
                # within a small window (e.g. same second), we insert it.
                # ACTUALLY, simpler:
                # existing_bankruptcy_timestamps is a set of strings.
                # We will insert a bankruptcy event with the SAME timestamp as the triggering event if it doesn't exist.

                for event_type, amount, created_at in events:
                    if event_type == "bankruptcy":
                        continue

                    val = amount if amount is not None else 0
                    balance += val

                    if balance <= 0:
                        if not was_bankrupt:
                            bk_count += 1
                            was_bankrupt = True

                            # Check if we need to insert event
                            # We look for a bankruptcy event at the exact same time (or extremely close)
                            # Since we want to attribute it to this moment, let's check if we have one.
                            # To be safe, let's insert if we don't find one with EXACT timestamp.
                            # But timestamps might be slightly different if logged sequentially.
                            # Let's check if there is a bankruptcy event within +/- 1 second?
                            # For simplicity/robustness: if we are backfilling, we can just insert with the timestamp of the trigger.
                            # But we must avoid creating duplicates if we run this script multiple times.

                            # Let's assume if we found a bankruptcy state transition, we should have an event.
                            # If existing_bankruptcy_timestamps has this created_at, skip.
                            # But created_at is string.

                            if created_at not in existing_bankruptcy_timestamps:
                                import uuid

                                # Insert missing bankruptcy event
                                # We use the timestamp of the event that caused bankruptcy
                                await db.execute(
                                    "INSERT INTO event_history (event_id, user_id, event_type, amount, created_at) VALUES (?, ?, 'bankruptcy', 0, ?)",
                                    (str(uuid.uuid4()), user_id, created_at),
                                )
                                # Add to set to avoid duplicate if we iterate again (though we iterate list copy)
                                existing_bankruptcy_timestamps.add(created_at)
                                print(
                                    f"Backfilled bankruptcy event for user {user_id} at {created_at}"
                                )

                    else:
                        was_bankrupt = False

                # Update user stats
                if bk_count > 0:
                    await db.execute(
                        "UPDATE users SET bankruptcy_count = ? WHERE user_id = ?",
                        (bk_count, user_id),
                    )

            await db.commit()
        print("Bankruptcy backfill completed.")

    async def get_balance(self, user_id: int, default_balance: int = 0) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT balance FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]

                # Если пользователя нет, создаем его
                await db.execute(
                    "INSERT INTO users (user_id, balance, bid) VALUES (?, ?, 1)",
                    (user_id, default_balance),
                )
                await db.commit()
                return default_balance

    async def update_balance(self, user_id: int, amount: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id)
            )
            await db.commit()
            add_db_action(f"Updated balance for user {user_id} by {amount}")

    async def set_balance(self, user_id: int, new_balance: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id)
            )
            await db.commit()
            add_db_action(f"Set balance for user {user_id} to {new_balance}")

    async def get_bid(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT bid FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                # Default bid is 1 if not set (though schema has default 1)
                return row[0] if row and row[0] is not None else 1

    async def update_bid(self, user_id: int, new_bid: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET bid = ? WHERE user_id = ?", (new_bid, user_id))
            await db.commit()
            add_db_action(f"Updated bid for user {user_id} to {new_bid}")

    async def get_user_by_nickname(self, nickname: str):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Remove @ if present
            clean_nickname = nickname.lstrip("@")
            async with db.execute(
                "SELECT * FROM users WHERE nickname = ? COLLATE NOCASE", (clean_nickname,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user(self, user_id: int) -> User | None:
        """Get user from DB; returns Pydantic User model or None."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                d = dict(row)
                # Normalize for User model (missing columns get defaults)
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

    async def register_user(self, user_id: int, nickname: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, nickname, balance, bid) VALUES (?, ?, 50, 1)",
                (user_id, nickname),
            )
            # Always update nickname in case it changed
            await db.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
            await db.commit()
            add_db_action(f"Registered/Updated user {user_id} ({nickname})")

    async def update_user_state(self, user_id: int, state: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET state = ? WHERE user_id = ?", (state, user_id))
            await db.commit()
            add_db_action(f"Updated state for user {user_id} to {state}")

    async def update_user_stats(self, user_id: int, amount: int, is_bankruptcy: bool = False):
        async with aiosqlite.connect(self.db_path) as db:
            won_add = amount if amount > 0 else 0
            lost_add = abs(amount) if amount < 0 else 0
            bankruptcy_add = 1 if is_bankruptcy else 0

            await db.execute(
                """
                UPDATE users
                SET games_played = games_played + 1,
                    total_won = total_won + ?,
                    total_lost = total_lost + ?,
                    bankruptcy_count = bankruptcy_count + ?
                WHERE user_id = ?
            """,
                (won_add, lost_add, bankruptcy_add, user_id),
            )
            await db.commit()
            add_db_action(
                f"Updated stats for user {user_id}: won={won_add}, lost={lost_add}, bankrupt={bankruptcy_add}"
            )

    async def add_event(
        self,
        event_id: str,
        user_id: int,
        event_type: str,
        amount: int,
        metadata: str = None,
        chat_id: int = None,
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO event_history (event_id, user_id, event_type, amount, metadata, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, user_id, event_type, amount, metadata, chat_id),
            )
            await db.commit()
            add_db_action(
                f"Added event {event_id} for user {user_id}: {event_type}, amount={amount}, chat={chat_id}"
            )

    async def add_event_from_model(self, event: GameEvent) -> None:
        """Add event to history from a Pydantic GameEvent model."""
        metadata_str = json.dumps(event.metadata) if event.metadata else None
        await self.add_event(
            event_id=event.event_id,
            user_id=event.user_id,
            event_type=event.event_type,
            amount=event.amount,
            metadata=metadata_str,
            chat_id=event.chat_id,
        )

    async def get_last_credit_event(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT created_at FROM event_history WHERE user_id = ? AND event_type = 'credit_grant' ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def transfer_money(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
        event_id_out: str,
        event_id_in: str,
        chat_id: int = None,
    ):
        async with aiosqlite.connect(self.db_path) as db:
            # Check balance
            async with db.execute(
                "SELECT balance FROM users WHERE user_id = ?", (from_user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] < amount:
                    return False

            # Transaction
            try:
                await db.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                    (amount, from_user_id),
                )
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_user_id)
                )

                await db.execute(
                    "INSERT INTO event_history (event_id, user_id, event_type, amount, chat_id) VALUES (?, ?, 'transfer_out', ?, ?)",
                    (event_id_out, from_user_id, -amount, chat_id),
                )
                await db.execute(
                    "INSERT INTO event_history (event_id, user_id, event_type, amount, chat_id) VALUES (?, ?, 'transfer_in', ?, ?)",
                    (event_id_in, to_user_id, amount, chat_id),
                )

                # Check for bankruptcy for sender
                # row[0] was old balance
                new_balance = row[0] - amount
                if new_balance <= 0:
                    import uuid

                    await db.execute(
                        "INSERT INTO event_history (event_id, user_id, event_type, amount, chat_id) VALUES (?, ?, 'bankruptcy', 0, ?)",
                        (str(uuid.uuid4()), from_user_id, chat_id),
                    )
                    await db.execute(
                        "UPDATE users SET bankruptcy_count = bankruptcy_count + 1 WHERE user_id = ?",
                        (from_user_id,),
                    )

                await db.commit()
                add_db_action(
                    f"Transferred {amount} from {from_user_id} to {to_user_id} in chat {chat_id}"
                )
                return True
            except Exception:
                # aiosqlite context manager automatically rolls back on exception if not committed,
                # but we are inside a context manager for connect, not transaction.
                # However, without BEGIN TRANSACTION explicitly, sqlite is in auto-commit mode usually,
                # but aiosqlite might handle it.
                # Ideally we should use `await db.execute("BEGIN TRANSACTION")` but let's trust the context or simple sequential execution for now.
                # Actually aiosqlite connect context commits at the end if no error.
                # If we raise here, it might rollback.
                # Let's add explicit rollback just in case.
                await db.rollback()
                return False

    async def create_credit_session(self, session_id: str, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO ai_credit_sessions (session_id, user_id, status) VALUES (?, ?, 'active')",
                (session_id, user_id),
            )
            await db.commit()

    async def get_active_session(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM ai_credit_sessions WHERE user_id = ? AND status IN ('active', 'processing')",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def set_session_processing(self, session_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE ai_credit_sessions SET status = 'processing' WHERE session_id = ? AND status = 'active'",
                (session_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def terminate_all_active_sessions(self):
        """Force close all active AI credit sessions on bot startup."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE ai_credit_sessions SET status = 'terminated', finished_at = CURRENT_TIMESTAMP WHERE status IN ('active', 'processing')"
            )
            await db.commit()

    async def close_credit_session(self, session_id: str, status: str, score: int, reward: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE ai_credit_sessions
                   SET status = ?, ai_score = ?, reward_amount = ?, finished_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (status, score, reward, session_id),
            )
            await db.commit()

    async def add_dialogue_message(self, session_id: str, role: str, content: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO ai_dialogue_messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            await db.commit()

    async def get_dialogue_history(self, session_id: str, limit: int = 10):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT role, content FROM ai_dialogue_messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                # We want the last N messages, but in chronological order.
                # SQL: ORDER BY created_at DESC LIMIT N -> then reverse in python
                return [dict(row) for row in rows][-limit:]

    async def update_user_group(self, user_id: int, chat_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO user_groups (user_id, chat_id, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (user_id, chat_id),
            )
            await db.commit()
            add_db_action(f"Updated user group for user {user_id} in chat {chat_id}")

    async def get_daily_stats(self, start_time_utc: str, end_time_utc: str, chat_id: int = None):
        """
        Aggregates stats for all users within the given time range.
        Returns a list of dicts with user stats.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # We aggregate by user_id
            # We need:
            # - total games (count of win/loss)
            # - total won (sum of positive amounts in win/loss)
            # - total lost (sum of abs negative amounts in win/loss)
            # - bankruptcy count (count of bankruptcy events)
            # - total given (sum of abs amounts in transfer_out)
            # - max win (max positive amount in win/loss)

            # Note: SQLite doesn't have a simple pivot, so we use conditional aggregation.
            # Added: avg_bid calculation (parsing JSON is expensive but feasible for daily stats)
            # We extract 'bid' from metadata JSON if event_type is win/loss
            query = """
                SELECT
                    u.user_id,
                    u.nickname,
                    COUNT(CASE WHEN eh.event_type IN ('win', 'loss') THEN 1 END) as games_played,
                    SUM(CASE WHEN eh.event_type IN ('win') AND eh.amount > 0 THEN eh.amount ELSE 0 END) as total_won,
                    SUM(CASE WHEN eh.event_type IN ('loss') AND eh.amount < 0 THEN ABS(eh.amount) ELSE 0 END) as total_lost,
                    SUM(CASE WHEN eh.event_type = 'bankruptcy' THEN 1 ELSE 0 END) as bankruptcy_count,
                    SUM(CASE WHEN eh.event_type = 'transfer_out' THEN ABS(eh.amount) ELSE 0 END) as total_given,
                    MAX(CASE WHEN eh.event_type IN ('win') THEN eh.amount ELSE 0 END) as max_win_amount,
                    AVG(CASE WHEN eh.event_type IN ('win', 'loss') AND eh.metadata IS NOT NULL THEN CAST(json_extract(eh.metadata, '$.bid') AS INTEGER) ELSE NULL END) as avg_bid
                FROM users u
                JOIN event_history eh ON u.user_id = eh.user_id
                WHERE eh.created_at BETWEEN ? AND ?
            """

            params = [start_time_utc, end_time_utc]
            if chat_id:
                query += " AND eh.chat_id = ?"
                params.append(chat_id)

            query += " GROUP BY u.user_id, u.nickname"

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_top_users_in_group(self, chat_id: int, limit: int = 30):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    u.user_id,
                    u.nickname,
                    u.balance,
                    COALESCE(stats.games_played, 0) as games_played,
                    COALESCE(stats.total_won, 0) as total_won,
                    COALESCE(stats.total_lost, 0) as total_lost,
                    COALESCE(stats.bankruptcy_count, 0) as bankruptcy_count
                FROM users u
                JOIN user_groups ug ON u.user_id = ug.user_id
                LEFT JOIN (
                    SELECT
                        user_id,
                        COUNT(CASE WHEN event_type IN ('win', 'loss') THEN 1 END) as games_played,
                        SUM(CASE WHEN event_type IN ('win') AND amount > 0 THEN amount ELSE 0 END) as total_won,
                        SUM(CASE WHEN event_type IN ('loss') AND amount < 0 THEN ABS(amount) ELSE 0 END) as total_lost,
                        SUM(CASE WHEN event_type = 'bankruptcy' THEN 1 ELSE 0 END) as bankruptcy_count
                    FROM event_history
                    WHERE chat_id = ?
                    GROUP BY user_id
                ) stats ON u.user_id = stats.user_id
                WHERE ug.chat_id = ?
                ORDER BY u.balance DESC
                LIMIT ?
                """,
                (chat_id, chat_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
