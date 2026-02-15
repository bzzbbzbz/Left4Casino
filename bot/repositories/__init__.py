# [START SPEC:TASK-010:repository-factory]
"""Repository factory for dependency injection."""

from bot.repositories.challenge import ChallengeRepository
from bot.repositories.debt import DebtRepository
from bot.repositories.event import EventRepository
from bot.repositories.user import UserRepository


class RepositoryFactory:
    """Factory for creating repositories with shared DB path."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def create_user_repo(self) -> UserRepository:
        return UserRepository(self.db_path)

    def create_event_repo(self) -> EventRepository:
        return EventRepository(self.db_path)

    def create_challenge_repo(self) -> ChallengeRepository:
        return ChallengeRepository(self.db_path)

    def create_debt_repo(self) -> DebtRepository:
        return DebtRepository(self.db_path)


__all__ = [
    "RepositoryFactory",
    "UserRepository",
    "EventRepository",
    "ChallengeRepository",
    "DebtRepository",
]

# [END SPEC:TASK-010:repository-factory]
