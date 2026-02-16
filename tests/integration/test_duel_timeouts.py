"""Integration tests for duel timeout flows and auto-roll finalization."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from bot.handlers.dice_fight import auto_roll_for_timeout
from bot.repositories import RepositoryFactory


async def _set_timestamp_minutes_ago(
    db_path: str, challenge_id: str, column_name: str, minutes: int
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE dice_challenges SET {column_name} = datetime('now', ?) WHERE challenge_id = ?",
            (f"-{minutes} minutes", challenge_id),
        )
        await db.commit()


async def _event_types(db_path: str, chat_id: int) -> list[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT event_type FROM event_history WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [row[0] for row in rows]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_expired_challenges_with_message_returns_only_old_pending(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    challenge_repo = repo_factory.create_challenge_repo()
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(901, "old_pending")
    await user_repo.register_user(902, "fresh_pending")

    await challenge_repo.create_dice_challenge(
        challenge_id="pending-old",
        chat_id=-100200300400,
        initiator_id=901,
        nickname="old_pending",
        first_name="old_pending",
        bet=10,
        going_debt=False,
        message_id=10,
    )
    await challenge_repo.create_dice_challenge(
        challenge_id="pending-fresh",
        chat_id=-100200300400,
        initiator_id=902,
        nickname="fresh_pending",
        first_name="fresh_pending",
        bet=10,
        going_debt=False,
        message_id=11,
    )

    await _set_timestamp_minutes_ago(test_db.db_path, "pending-old", "created_at", 10)
    expired = await challenge_repo.get_expired_challenges_with_message(timeout_minutes=5)

    expired_ids = {c["challenge_id"] for c in expired}
    assert "pending-old" in expired_ids
    assert "pending-fresh" not in expired_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_timed_out_duels_returns_only_old_unfinished_duels(test_db) -> None:
    repo_factory = RepositoryFactory(test_db.db_path)
    challenge_repo = repo_factory.create_challenge_repo()
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(911, "initiator")
    await user_repo.register_user(912, "opponent")
    await user_repo.register_user(913, "fresh")
    await user_repo.register_user(914, "freshopp")

    await challenge_repo.create_dice_challenge(
        challenge_id="duel-old",
        chat_id=-100500600700,
        initiator_id=911,
        nickname="initiator",
        first_name="initiator",
        bet=15,
        going_debt=False,
        message_id=21,
    )
    await challenge_repo.accept_challenge("duel-old", 912, "opponent", "opponent")
    await _set_timestamp_minutes_ago(test_db.db_path, "duel-old", "accepted_at", 10)

    await challenge_repo.create_dice_challenge(
        challenge_id="duel-fresh",
        chat_id=-100500600700,
        initiator_id=913,
        nickname="fresh",
        first_name="fresh",
        bet=15,
        going_debt=False,
        message_id=22,
    )
    await challenge_repo.accept_challenge("duel-fresh", 914, "freshopp", "freshopp")

    timed_out = await challenge_repo.get_timed_out_duels(timeout_minutes=5)
    timed_out_ids = {c["challenge_id"] for c in timed_out}
    assert "duel-old" in timed_out_ids
    assert "duel-fresh" not in timed_out_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_roll_for_timeout_completes_duel_with_valid_outcome(test_db) -> None:
    chat_id = -100111222333
    repo_factory = RepositoryFactory(test_db.db_path)
    challenge_repo = repo_factory.create_challenge_repo()
    user_repo = repo_factory.create_user_repo()

    await user_repo.register_user(921, "alpha")
    await user_repo.register_user(922, "beta")
    await user_repo.set_balance(921, 50)
    await user_repo.set_balance(922, 50)

    await challenge_repo.create_dice_challenge(
        challenge_id="duel-timeout-finalize",
        chat_id=chat_id,
        initiator_id=921,
        nickname="alpha",
        first_name="Alpha",
        bet=10,
        going_debt=False,
        message_id=31,
    )
    await challenge_repo.accept_challenge("duel-timeout-finalize", 922, "beta", "Beta")

    challenge = await challenge_repo.get_challenge("duel-timeout-finalize")
    assert challenge is not None

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch("bot.handlers.dice_fight.random.randint", side_effect=[6, 1]):
        with patch("bot.handlers.dice_fight.random.choice", side_effect=lambda seq: seq[0]):
            await auto_roll_for_timeout(repo_factory, bot, challenge)

    finished = await challenge_repo.get_challenge("duel-timeout-finalize")
    assert finished is not None
    assert finished["status"] == "completed"
    assert finished["initiator_roll"] is not None
    assert finished["opponent_roll"] is not None

    event_types = await _event_types(test_db.db_path, chat_id)
    assert "dice_challenge_win" in event_types
    assert "dice_challenge_loss" in event_types
