# [START SPEC:TASK-007:migration-runner]
"""Database migration runner. Applies versioned SQL migrations to the bot database."""

import argparse
import asyncio
import os
import re
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


def _split_top_level_csv(sql: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for index, char in enumerate(sql):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ('"', "'", "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(sql[start:index].strip())
            start = index + 1
    parts.append(sql[start:].strip())
    return parts


def _replace_column_type(definition: str, money_columns: set[str]) -> str:
    match = re.match(
        r'^(?P<indent>\s*)(?P<name>"[^"]+"|`[^`]+`|\[[^\]]+\]|\w+)(?P<rest>\s+.*)?$',
        definition,
        flags=re.DOTALL,
    )
    if not match:
        return definition
    raw_name = match.group("name")
    column_name = raw_name.strip('"`[]')
    if column_name not in money_columns:
        return definition

    rest = (match.group("rest") or "").lstrip()
    constraints = (
        "PRIMARY",
        "NOT",
        "NULL",
        "DEFAULT",
        "CHECK",
        "COLLATE",
        "REFERENCES",
        "UNIQUE",
        "GENERATED",
        "AS",
    )
    tokens = rest.split(None, 1)
    if tokens and tokens[0].upper() not in constraints:
        rest = tokens[1] if len(tokens) == 2 else ""
    if "DEFAULT" in rest.upper():
        rest = re.sub(
            r"(?i)\bDEFAULT\s+([+-]?\d+|'[+-]?\d+'|\"[+-]?\d+\")",
            lambda m: f"DEFAULT '{m.group(1).strip(chr(39) + chr(34))}'",
            rest,
            count=1,
        )
    suffix = f" {rest}" if rest else ""
    return f"{match.group('indent')}{raw_name} TEXT{suffix}"


async def _table_create_sql(db: aiosqlite.Connection, table: str) -> str:
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(f"Cannot find CREATE TABLE SQL for {table}")
    return str(row[0])


def _money_text_create_sql(create_sql: str, table: str) -> str:
    money_columns = MONEY_COLUMN_TYPES.get(table, set())
    open_index = create_sql.index("(")
    close_index = create_sql.rindex(")")
    prefix = create_sql[:open_index]
    body = create_sql[open_index + 1 : close_index]
    suffix = create_sql[close_index + 1 :]
    definitions = [_replace_column_type(part, money_columns) for part in _split_top_level_csv(body)]
    return f"{prefix}({', '.join(definitions)}){suffix}"


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
    original_create_sqls: dict[str, str] = {}
    for table in MONEY_COLUMN_TYPES:
        if await _table_exists(db, table):
            original_create_sqls[table] = await _table_create_sql(db, table)

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
        create_sql = _money_text_create_sql(original_create_sqls[table], table)
        quoted_cols = ", ".join(f'"{name}"' for name in col_names)
        select_exprs = []
        for name in col_names:
            if name in money_columns:
                select_exprs.append(f'CAST("{name}" AS TEXT) AS "{name}"')
            else:
                select_exprs.append(f'"{name}"')
        await db.execute(f'DROP TABLE IF EXISTS "{tmp}"')
        await db.execute(f'ALTER TABLE "{table}" RENAME TO "{tmp}"')
        await db.execute(create_sql)
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
    if not await _table_exists(db, "schema_versions"):
        return 0
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
        if dry_run:
            report = await apply_bigint_money_migration(db, dry_run=True)
            print(f"  TASK-016 money migration report: {report}")
            return
        fk_row = await (await db.execute("PRAGMA foreign_keys")).fetchone()
        legacy_alter_row = await (await db.execute("PRAGMA legacy_alter_table")).fetchone()
        foreign_keys_enabled = bool(fk_row and fk_row[0])
        legacy_alter_enabled = bool(legacy_alter_row and legacy_alter_row[0])
        try:
            await db.execute("PRAGMA foreign_keys = OFF")
            await db.execute("PRAGMA legacy_alter_table = ON")
            await db.execute("BEGIN IMMEDIATE")
            report = await apply_bigint_money_migration(db)
            print(f"  TASK-016 money migration report: {report}")
            await db.execute(
                """INSERT INTO schema_versions (version, applied_at, description)
                   VALUES (?, datetime('now'), ?)""",
                (version, migration_file.name),
            )
            await db.commit()
            if not legacy_alter_enabled:
                await db.execute("PRAGMA legacy_alter_table = OFF")
            if foreign_keys_enabled:
                await db.execute("PRAGMA foreign_keys = ON")
            print(f"  ✓ Migration {version} applied successfully")
        except Exception:
            await db.rollback()
            if not legacy_alter_enabled:
                await db.execute("PRAGMA legacy_alter_table = OFF")
            if foreign_keys_enabled:
                await db.execute("PRAGMA foreign_keys = ON")
            raise
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
        if not dry_run:
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
