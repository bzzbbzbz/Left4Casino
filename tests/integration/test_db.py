"""Integration tests for database operations."""

import uuid

import pytest
from bot.db import Database


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transfer_money_atomic_transaction(test_db: Database) -> None:
    """Transfer is atomic: both users updated or neither."""
    sender_id = 111
    receiver_id = 222
    amount = 50

    await test_db.get_balance(sender_id, 100)  # create sender with 100
    await test_db.get_balance(receiver_id, 50)  # create receiver with 50
    await test_db.set_balance(sender_id, 100)
    await test_db.set_balance(receiver_id, 50)

    event_id_out = str(uuid.uuid4())
    event_id_in = str(uuid.uuid4())
    result = await test_db.transfer_money(
        from_user_id=sender_id,
        to_user_id=receiver_id,
        amount=amount,
        event_id_out=event_id_out,
        event_id_in=event_id_in,
        chat_id=None,
    )

    assert result is True
    sender_balance = await test_db.get_balance(sender_id, 0)
    receiver_balance = await test_db.get_balance(receiver_id, 0)
    assert sender_balance == 50
    assert receiver_balance == 100


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_balance_creates_user_with_default(test_db: Database) -> None:
    """get_balance creates user with default_balance when user does not exist."""
    new_user_id = 999888
    balance = await test_db.get_balance(new_user_id, 75)
    assert balance == 75
    user = await test_db.get_user(new_user_id)
    assert user is not None
    assert user.balance == 75
