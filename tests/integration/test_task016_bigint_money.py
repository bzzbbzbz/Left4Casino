"""Integration coverage for TASK-016 bigint money storage."""

import os
import tempfile
import uuid

import aiosqlite
import pytest

from bot.db import Database
from bot.repositories import RepositoryFactory
from migrations.migration_runner import init_schema_versions_table, run_migrations


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
                    chat_id INTEGER
                )"""
            )
            await db.execute(
                """CREATE TABLE ai_credit_sessions (
                    session_id TEXT PRIMARY KEY, user_id INTEGER, status TEXT DEFAULT 'active',
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP, finished_at DATETIME,
                    ai_score INTEGER, reward_amount INTEGER
                )"""
            )
            await db.execute(
                """CREATE TABLE dice_challenges (
                    challenge_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, initiator_id INTEGER NOT NULL,
                    bet_amount INTEGER NOT NULL, initiator_going_debt INTEGER DEFAULT 0
                )"""
            )
            await db.execute(
                """CREATE TABLE player_debts (
                    debt_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, debtor_id INTEGER NOT NULL,
                    creditor_id INTEGER NOT NULL, amount INTEGER NOT NULL,
                    UNIQUE(chat_id, debtor_id, creditor_id)
                )"""
            )
            await db.execute(
                "INSERT INTO users (user_id, balance, bid, safe_balance, total_won, total_lost, last_dice_bet) VALUES (1, 50, 1, 0, 1, 50, 50)"
            )
            await db.execute(
                "INSERT INTO event_history (event_id, user_id, event_type, amount) VALUES ('e1', 1, 'loss', -50)"
            )
            await db.execute(
                "INSERT INTO ai_credit_sessions (session_id, user_id, reward_amount) VALUES ('s1', 1, NULL)"
            )
            await db.execute(
                "INSERT INTO dice_challenges (challenge_id, chat_id, initiator_id, bet_amount, initiator_going_debt) VALUES ('c1', 1, 1, 50, 1)"
            )
            await db.execute(
                "INSERT INTO player_debts (debt_id, chat_id, debtor_id, creditor_id, amount) VALUES ('d1', 1, 1, 2, 50)"
            )
            await db.commit()

        await run_migrations(db_path=path)

        async with aiosqlite.connect(path) as db:
            user_cols = {
                row[1]: row[2]
                for row in await (await db.execute("PRAGMA table_info(users)")).fetchall()
            }
            challenge_cols = {
                row[1]: row[2]
                for row in await (await db.execute("PRAGMA table_info(dice_challenges)")).fetchall()
            }
            assert user_cols["balance"].upper() == "TEXT"
            assert challenge_cols["bet_amount"].upper() == "TEXT"
            assert challenge_cols["initiator_going_debt"].upper() == "INTEGER"
            row = await (
                await db.execute("SELECT balance, last_dice_bet FROM users WHERE user_id = 1")
            ).fetchone()
            assert row == ("50", "50")
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
    for user_id, nickname, balance in [(1, "small", 9), (2, "big", 10**24), (3, "medium", 50)]:
        await test_db.register_user(user_id, nickname)
        await test_db.set_balance(user_id, balance)
        await test_db.update_user_group(user_id, chat_id)
        await test_db.add_event(str(uuid.uuid4()), user_id, "win", 1, chat_id=chat_id)

    top_users = await test_db.get_top_users_in_group(chat_id, limit=3)
    assert [user["nickname"] for user in top_users] == ["big", "medium", "small"]
