# [START SPEC:TASK-010:protocol-interfaces]
"""Protocol interfaces for testing (mock repositories)."""

from typing import Any, Protocol

from bot.models.entities import User
from bot.models.events import GameEvent


class IUserRepository(Protocol):
    """Interface for user repository (for mocking)."""

    async def get_by_id(self, user_id: int) -> User | None: ...
    async def get_balance(self, user_id: int, default_balance: int = 0) -> int: ...
    async def update_balance(self, user_id: int, amount: int) -> None: ...
    async def set_balance(self, user_id: int, new_balance: int) -> None: ...
    async def transfer(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: int,
    ) -> bool: ...
    async def get_safe_balance(self, user_id: int) -> int: ...
    async def safe_deposit(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]: ...
    async def safe_withdraw(
        self, user_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]: ...


class IEventRepository(Protocol):
    """Interface for event repository."""

    async def add(self, event: GameEvent) -> None: ...
    async def add_event(
        self,
        event_id: str,
        user_id: int,
        event_type: str,
        amount: int,
        metadata: str | None = None,
        chat_id: int | None = None,
    ) -> None: ...
    async def get_user_events(self, user_id: int, limit: int = 100) -> list[GameEvent]: ...
    async def get_last_credit_event(self, user_id: int) -> dict[str, Any] | None: ...


class IChallengeRepository(Protocol):
    """Interface for dice challenge repository."""

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
    ) -> None: ...
    async def get_challenge(self, challenge_id: str) -> dict[str, Any] | None: ...
    async def get_active_challenge_by_user(
        self, user_id: int, chat_id: int
    ) -> dict[str, Any] | None: ...
    async def get_accepted_challenge_for_user(
        self, user_id: int, chat_id: int
    ) -> dict[str, Any] | None: ...
    async def accept_challenge(
        self,
        challenge_id: str,
        opponent_id: int,
        opponent_nickname: str | None,
        opponent_first_name: str | None,
    ) -> bool: ...
    async def record_roll(self, challenge_id: str, user_id: int, roll_value: int) -> None: ...
    async def complete_challenge(self, challenge_id: str, winner_id: int | None) -> None: ...
    async def cancel_challenge(self, challenge_id: str) -> None: ...
    async def get_last_dice_bet(self, user_id: int) -> int | None: ...
    async def set_last_dice_bet(self, user_id: int, bet: int) -> None: ...


class IDebtRepository(Protocol):
    """Interface for debt repository."""

    async def get_debt(
        self, chat_id: int, debtor_id: int, creditor_id: int
    ) -> dict[str, Any] | None: ...
    async def get_total_debt(self, user_id: int, chat_id: int) -> int: ...
    async def create_or_update_debt(
        self,
        debtor_id: int,
        creditor_id: int,
        amount: int,
        chat_id: int,
        challenge_id: str,
    ) -> None: ...
    async def collect_debt(
        self, creditor_id: int, debtor_id: int, amount: int, chat_id: int
    ) -> tuple[bool, int, int] | tuple[bool, str]: ...


# [END SPEC:TASK-010:protocol-interfaces]
