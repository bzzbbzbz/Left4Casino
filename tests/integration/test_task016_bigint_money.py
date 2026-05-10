"""Integration coverage for TASK-016 bigint money storage."""

import os
import sqlite3
import tempfile
import uuid

import aiosqlite
import pytest

from bot.db import Database
from bot.repositories import RepositoryFactory
from migrations.migration_runner import init_schema_versions_table, run_migrations

MONEY_COLUMNS = {
    "users": {"balance", "bid", "safe_balance", "last_dice_bet", "total_won", "total_lost"},
    "event_history": {"amount"},
    "ai_credit_sessions": {"reward_amount"},
    "dice_challenges": {"bet_amount"},
    "player_debts": {"amount"},
}


async def _foreign_key_targets(db: aiosqlite.Connection, table: str) -> list[str]:
    rows = await (await db.execute(f"PRAGMA foreign_key_list({table})")).fetchall()
    return [row[2] for row in rows]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_converts_old_integer_money_schema_to_text() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        async with aiosqlite.connect(path) as db:
            await init_schema_versions_table(db)
            await db.execute(
                "INSERT INTO schema_versions VALUES (2, datetime('now'), 'pre-task016')"
            )
            await db.execute(
                """CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY, nickname TEXT, balance INTEGER NOT NULL DEFAULT 50,
                    bid INTEGER DEFAULT 1, state TEXT DEFAULT 'IDLE', created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    games_played INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0, total_lost INTEGER DEFAULT 0,
                    bankruptcy_count INTEGER DEFAULT 0, safe_balance INTEGER DEFAULT 0, last_dice_bet INTEGER
                )"""
            )
            await db.execute(
                """CREATE TABLE event_history (
                    event_id TEXT PRIMARY KEY, user_id INTEGER, event_type TEXT NOT NULL,
                    amount INTEGER DEFAULT 0, metadata TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    chat_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE ai_credit_sessions (
                    session_id TEXT PRIMARY KEY, user_id INTEGER, status TEXT DEFAULT 'active',
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP, finished_at DATETIME,
                    ai_score INTEGER, reward_amount INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE ai_dialogue_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES ai_credit_sessions (session_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE user_groups (
                    user_id INTEGER,
                    chat_id INTEGER,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, chat_id),
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE dice_challenges (
                    challenge_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, initiator_id INTEGER NOT NULL,
                    bet_amount INTEGER NOT NULL, initiator_going_debt INTEGER DEFAULT 0,
                    FOREIGN KEY (initiator_id) REFERENCES users (user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE player_debts (
                    debt_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, debtor_id INTEGER NOT NULL,
                    creditor_id INTEGER NOT NULL, amount INTEGER NOT NULL,
                    UNIQUE(chat_id, debtor_id, creditor_id),
                    FOREIGN KEY (debtor_id) REFERENCES users (user_id),
                    FOREIGN KEY (creditor_id) REFERENCES users (user_id)
                )"""
            )
            huge = str(10**24)
            await db.execute(
                "INSERT INTO users (user_id, balance, bid, safe_balance, total_won, total_lost, last_dice_bet) VALUES (1, 50, 1, 0, 1, 50, 50)"
            )
            await db.execute(
                "INSERT INTO users (user_id, balance, bid, safe_balance, total_won, total_lost, last_dice_bet) VALUES (2, CAST(? AS BLOB), 10, 1, CAST(? AS BLOB), 1, NULL)",
                (huge, huge),
            )
            await db.execute(
                "INSERT INTO event_history (event_id, user_id, event_type, amount) VALUES ('e1', 1, 'loss', -50)"
            )
            await db.execute(
                "INSERT INTO event_history (event_id, user_id, event_type, amount) VALUES ('e2', 2, 'win', CAST(? AS BLOB))",
                (huge,),
            )
            await db.execute(
                "INSERT INTO ai_credit_sessions (session_id, user_id, reward_amount) VALUES ('s1', 1, NULL)"
            )
            await db.execute(
                "INSERT INTO ai_credit_sessions (session_id, user_id, reward_amount) VALUES ('s2', 2, CAST(? AS BLOB))",
                (huge,),
            )
            await db.execute(
                "INSERT INTO ai_dialogue_messages (session_id, role, content) VALUES ('s1', 'user', 'hello')"
            )
            await db.execute("INSERT INTO user_groups (user_id, chat_id) VALUES (1, -100)")
            await db.execute(
                "INSERT INTO dice_challenges (challenge_id, chat_id, initiator_id, bet_amount, initiator_going_debt) VALUES ('c1', 1, 1, 50, 1)"
            )
            await db.execute(
                "INSERT INTO dice_challenges (challenge_id, chat_id, initiator_id, bet_amount, initiator_going_debt) VALUES ('c2', 1, 2, CAST(? AS BLOB), 0)",
                (huge,),
            )
            await db.execute(
                "INSERT INTO player_debts (debt_id, chat_id, debtor_id, creditor_id, amount) VALUES ('d1', 1, 1, 2, 50)"
            )
            await db.commit()

        await run_migrations(db_path=path)

        async with aiosqlite.connect(path) as db:
            for table, money_columns in MONEY_COLUMNS.items():
                cols = {
                    row[1]: row[2]
                    for row in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
                }
                for column in money_columns:
                    if column in cols:
                        assert cols[column].upper() == "TEXT"
            challenge_cols = {
                row[1]: row[2]
                for row in await (await db.execute("PRAGMA table_info(dice_challenges)")).fetchall()
            }
            assert challenge_cols["initiator_going_debt"].upper() == "INTEGER"
            assert await (await db.execute("SELECT COUNT(*) FROM users")).fetchone() == (2,)
            assert await (await db.execute("SELECT COUNT(*) FROM event_history")).fetchone() == (2,)
            assert await (
                await db.execute("SELECT COUNT(*) FROM ai_credit_sessions")
            ).fetchone() == (2,)
            assert await (
                await db.execute("SELECT COUNT(*) FROM ai_dialogue_messages")
            ).fetchone() == (1,)
            assert await (await db.execute("SELECT COUNT(*) FROM user_groups")).fetchone() == (1,)
            assert await (await db.execute("SELECT COUNT(*) FROM dice_challenges")).fetchone() == (
                2,
            )
            assert await (await db.execute("SELECT COUNT(*) FROM player_debts")).fetchone() == (1,)
            row = await (
                await db.execute(
                    "SELECT balance, bid, safe_balance, total_won, total_lost, last_dice_bet FROM users WHERE user_id = 1"
                )
            ).fetchone()
            assert row == ("50", "1", "0", "1", "50", "50")
            huge_row = await (
                await db.execute("SELECT balance, total_won FROM users WHERE user_id = 2")
            ).fetchone()
            assert huge_row == (str(10**24), str(10**24))
            challenge_row = await (
                await db.execute(
                    "SELECT bet_amount, initiator_going_debt FROM dice_challenges WHERE challenge_id = 'c1'"
                )
            ).fetchone()
            assert challenge_row == ("50", 1)
            event_row = await (
                await db.execute("SELECT amount FROM event_history WHERE event_id = 'e2'")
            ).fetchone()
            assert event_row == (str(10**24),)
            reward_row = await (
                await db.execute(
                    "SELECT reward_amount FROM ai_credit_sessions WHERE session_id = 's2'"
                )
            ).fetchone()
            assert reward_row == (str(10**24),)
            challenge_huge_row = await (
                await db.execute("SELECT bet_amount FROM dice_challenges WHERE challenge_id = 'c2'")
            ).fetchone()
            assert challenge_huge_row == (str(10**24),)
            debt_row = await (
                await db.execute("SELECT amount FROM player_debts WHERE debt_id = 'd1'")
            ).fetchone()
            assert debt_row == ("50",)
            assert await _foreign_key_targets(db, "event_history") == ["users"]
            assert await _foreign_key_targets(db, "ai_credit_sessions") == ["users"]
            assert await _foreign_key_targets(db, "dice_challenges") == ["users"]
            assert await _foreign_key_targets(db, "player_debts") == ["users", "users"]
            assert await _foreign_key_targets(db, "user_groups") == ["users"]
            assert await _foreign_key_targets(db, "ai_dialogue_messages") == ["ai_credit_sessions"]
    finally:
        os.unlink(path)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_dry_run_does_not_mutate_empty_database() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await run_migrations(dry_run=True, db_path=path)
        with sqlite3.connect(path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert rows == []
    finally:
        os.unlink(path)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_huge_transfers_safe_and_debts(test_db: Database) -> None:
    huge = 10**24
    repo_factory = RepositoryFactory(test_db.db_path)
    user_repo = repo_factory.create_user_repo()
    debt_repo = repo_factory.create_debt_repo()

    await user_repo.register_user(9001, "rich")
    await user_repo.register_user(9002, "other")
    await user_repo.set_balance(9001, huge)
    await user_repo.set_balance(9002, 0)

    assert await user_repo.transfer(9001, 9002, huge // 2)
    assert await user_repo.get_balance(9001) == huge // 2
    assert await user_repo.get_balance(9002) == huge // 2

    assert await user_repo.safe_deposit(9002, huge // 4, -100) == (
        True,
        huge // 4,
        huge // 4,
    )
    await debt_repo.create_or_update_debt(9002, 9001, huge // 8, -100, "challenge-big")
    assert await debt_repo.get_total_debt(9002, -100) == huge // 8
    assert await debt_repo.collect_debt(9001, 9002, huge // 16, -100) == (
        True,
        huge // 16,
        huge // 16,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_top_uses_numeric_ordering_for_text_money(test_db: Database) -> None:
    chat_id = -1001234567890
    balances = [
        (1, "nine", 9),
        (2, "ten", 10),
        (3, "hundred", 100),
        (4, "exa", 10**18),
        (5, "huge", 10**24),
    ]
    for user_id, nickname, balance in balances:
        await test_db.register_user(user_id, nickname)
        await test_db.set_balance(user_id, balance)
        await test_db.update_user_group(user_id, chat_id)
        await test_db.add_event(str(uuid.uuid4()), user_id, "win", 1, chat_id=chat_id)

    top_users = await test_db.get_top_users_in_group(chat_id, limit=5)
    assert [user["nickname"] for user in top_users] == ["huge", "exa", "hundred", "ten", "nine"]
