# [START SPEC:TASK-007:migration-runner]
"""Database migration runner. Applies versioned SQL migrations to the bot database."""

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

import aiosqlite

MIGRATIONS_DIR = Path(__file__).resolve().parent
# Default: bot/casino.db relative to project root (python-runner)
_DEFAULT_DB_PATH = MIGRATIONS_DIR.parent / "bot" / "casino.db"
DB_PATH = os.environ.get("CASINO_DB_PATH", str(_DEFAULT_DB_PATH))


# [START SPEC:TASK-016:bigint-money-migration]
# REQ: Convert persisted money storage from INTEGER to TEXT without scale factors or REAL.
# Source: TASK-016 Big Integer Money Storage exact design.
# CRITICAL: Python migration path keeps large values as decimal strings and leaves boolean fields intact.
MONEY_COLUMN_TYPES: dict[str, set[str]] = {
    "users": {"balance", "bid", "safe_balance", "last_dice_bet", "total_won", "total_lost"},
    "event_history": {"amount"},
    "ai_credit_sessions": {"reward_amount"},
    "dice_challenges": {"bet_amount"},
    "player_debts": {"amount"},
}


def _column_def(table: str, col: aiosqlite.Row) -> str:
    name = col["name"]
    col_type = "TEXT" if name in MONEY_COLUMN_TYPES.get(table, set()) else (col["type"] or "")
    parts = [f'"{name}"', col_type]
    if col["pk"]:
        parts.append("PRIMARY KEY")
    if col["notnull"]:
        parts.append("NOT NULL")
    default = col["dflt_value"]
    if name in MONEY_COLUMN_TYPES.get(table, set()):
        if default is not None:
            default_text = str(default).strip("'")
            parts.append(f"DEFAULT '{default_text}'")
    elif default is not None:
        parts.append(f"DEFAULT {default}")
    return " ".join(part for part in parts if part)


async def _table_columns(db: aiosqlite.Connection, table: str) -> list[aiosqlite.Row]:
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(f'PRAGMA table_info("{table}")')
    return await cursor.fetchall()


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cursor = await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return await cursor.fetchone() is not None


async def apply_bigint_money_migration(
    db: aiosqlite.Connection, *, dry_run: bool = False
) -> dict[str, Any]:
    """Convert configured money columns to TEXT by rebuilding affected tables."""
    report: dict[str, Any] = {"tables": {}, "dry_run": dry_run}
    for table, money_columns in MONEY_COLUMN_TYPES.items():
        if not await _table_exists(db, table):
            report["tables"][table] = {"status": "missing"}
            continue

        columns = await _table_columns(db, table)
        existing_money = [col for col in columns if col["name"] in money_columns]
        needs_conversion = any((col["type"] or "").upper() != "TEXT" for col in existing_money)
        report["tables"][table] = {
            "status": "convert" if needs_conversion else "already_text",
            "money_columns": [col["name"] for col in existing_money],
        }
        if dry_run or not needs_conversion:
            continue

        tmp = f"{table}__task016_old"
        col_names = [col["name"] for col in columns]
        definitions = ", ".join(_column_def(table, col) for col in columns)
        quoted_cols = ", ".join(f'"{name}"' for name in col_names)
        select_exprs = []
        for name in col_names:
            if name in money_columns:
                select_exprs.append(f'CAST("{name}" AS TEXT) AS "{name}"')
            else:
                select_exprs.append(f'"{name}"')
        await db.execute(f'DROP TABLE IF EXISTS "{tmp}"')
        await db.execute(f'ALTER TABLE "{table}" RENAME TO "{tmp}"')
        await db.execute(f'CREATE TABLE "{table}" ({definitions})')
        await db.execute(
            f'INSERT INTO "{table}" ({quoted_cols}) SELECT {", ".join(select_exprs)} FROM "{tmp}"'
        )
        await db.execute(f'DROP TABLE "{tmp}"')
    if not dry_run:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_history_user_id ON event_history (user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_history_created_at ON event_history (created_at)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_player_debts_unique ON player_debts (chat_id, debtor_id, creditor_id)"
        )
    return report


# [END SPEC:TASK-016]


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


async def apply_migration(
    db: aiosqlite.Connection, migration_file: Path, *, dry_run: bool = False
) -> None:
    """Apply single migration file: run UPGRADE section and record version."""
    stem = migration_file.stem
    prefix = stem.split("_")[0]
    if not prefix.isdigit():
        return
    version = int(prefix)

    print(f"Applying migration {version}: {migration_file.name}")

    if version == 3:
        report = await apply_bigint_money_migration(db, dry_run=dry_run)
        print(f"  TASK-016 money migration report: {report}")
        if dry_run:
            return
        await db.execute(
            """INSERT INTO schema_versions (version, applied_at, description)
               VALUES (?, datetime('now'), ?)""",
            (version, migration_file.name),
        )
        await db.commit()
        print(f"  ✓ Migration {version} applied successfully")
        return

    sql = migration_file.read_text()
    upgrade_sql = _extract_upgrade_sql(sql)
    if not upgrade_sql:
        print(f"  (no UPGRADE SQL in {migration_file.name}, skipping)")
        return

    if dry_run:
        print(f"  (dry-run: would execute {len(upgrade_sql)} bytes of SQL)")
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


async def run_migrations(*, dry_run: bool = False, db_path: str | None = None) -> int:
    """Run all pending migrations. Returns new schema version."""
    async with aiosqlite.connect(db_path or DB_PATH) as db:
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
            await apply_migration(db, migration_file, dry_run=dry_run)

        new_version = await get_current_version(db)
        print(f"\n✓ All migrations applied. New version: {new_version}")
        return new_version


# [END SPEC:TASK-007:migration-runner]


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run casino DB migrations")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report pending migrations without mutating DB"
    )
    parser.add_argument("--db-path", default=None, help="Override CASINO_DB_PATH for this run")
    args = parser.parse_args()
    asyncio.run(run_migrations(dry_run=args.dry_run, db_path=args.db_path))


if __name__ == "__main__":
    main()
