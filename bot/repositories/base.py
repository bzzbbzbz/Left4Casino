# [START SPEC:TASK-010:base-repository]
"""Base repository with common functionality."""

from typing import Generic, TypeVar

import aiosqlite

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base class for all repositories."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def _execute(self, query: str, params: tuple = ()) -> None:
        """Execute query and commit."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    async def _fetchone(self, query: str, params: tuple = ()) -> aiosqlite.Row | None:
        """Fetch single row."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchone()

    async def _fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Fetch all rows."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return await cursor.fetchall()

    def _connection(self) -> aiosqlite.Connection:
        """Return connection context (for transactions). Use: async with repo._connection() as db: ..."""
        return aiosqlite.connect(self.db_path)


# [END SPEC:TASK-010:base-repository]
