# [START SPEC:TASK-007:migration-runner]
"""Database migration runner. Applies versioned SQL migrations to the bot database."""

import asyncio
import os
from pathlib import Path

import aiosqlite

MIGRATIONS_DIR = Path(__file__).resolve().parent
# Default: bot/casino.db relative to project root (python-runner)
_DEFAULT_DB_PATH = MIGRATIONS_DIR.parent / "bot" / "casino.db"
DB_PATH = os.environ.get("CASINO_DB_PATH", str(_DEFAULT_DB_PATH))


async def init_schema_versions_table(db: aiosqlite.Connection) -> None:
    """Create schema_versions table if not exists."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
        """
    )
    await db.commit()


async def get_current_version(db: aiosqlite.Connection) -> int:
    """Get current schema version (max version from schema_versions)."""
    cursor = await db.execute("SELECT MAX(version) FROM schema_versions")
    result = await cursor.fetchone()
    return result[0] if result and result[0] is not None else 0


def _extract_upgrade_sql(sql: str) -> str:
    """Extract UPGRADE section from migration file (between -- UPGRADE and -- DOWNGRADE)."""
    if "-- UPGRADE" not in sql:
        return sql.strip()
    parts = sql.split("-- UPGRADE", 1)[1]
    if "-- DOWNGRADE" in parts:
        parts = parts.split("-- DOWNGRADE")[0]
    return parts.strip()


async def apply_migration(db: aiosqlite.Connection, migration_file: Path) -> None:
    """Apply single migration file: run UPGRADE section and record version."""
    stem = migration_file.stem
    prefix = stem.split("_")[0]
    if not prefix.isdigit():
        return
    version = int(prefix)

    print(f"Applying migration {version}: {migration_file.name}")

    sql = migration_file.read_text()
    upgrade_sql = _extract_upgrade_sql(sql)
    if not upgrade_sql:
        print(f"  (no UPGRADE SQL in {migration_file.name}, skipping)")
        return

    await db.executescript(upgrade_sql)

    await db.execute(
        """INSERT INTO schema_versions (version, applied_at, description)
           VALUES (?, datetime('now'), ?)""",
        (version, migration_file.name),
    )
    await db.commit()
    print(f"  ✓ Migration {version} applied successfully")


def _sorted_migration_files() -> list[Path]:
    """Return migration .sql files sorted by version number (001, 002, ...)."""
    files: list[Path] = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        stem = path.stem
        prefix = stem.split("_")[0]
        if prefix.isdigit():
            files.append((int(prefix), path))
    files.sort(key=lambda x: x[0])
    return [p for _, p in files]


async def run_migrations() -> int:
    """Run all pending migrations. Returns new schema version."""
    async with aiosqlite.connect(DB_PATH) as db:
        await init_schema_versions_table(db)
        current_version = await get_current_version(db)

        print(f"Current schema version: {current_version}")

        all_migrations = _sorted_migration_files()
        pending = [f for f in all_migrations if int(f.stem.split("_")[0]) > current_version]

        if not pending:
            print("No pending migrations")
            return current_version

        print(f"Found {len(pending)} pending migration(s)")

        for migration_file in pending:
            await apply_migration(db, migration_file)

        new_version = await get_current_version(db)
        print(f"\n✓ All migrations applied. New version: {new_version}")
        return new_version


# [END SPEC:TASK-007:migration-runner]


def main() -> None:
    """CLI entry point."""
    asyncio.run(run_migrations())


if __name__ == "__main__":
    main()
