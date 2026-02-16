# Database Migrations

Versioned SQL migrations for the Left4Casino bot database. Run from project root (`python-runner/`).

## Commands

```bash
# Apply all pending migrations (default DB: telegram-casino-bot/bot/casino.db)
python migrations/migration_runner.py

# Use custom DB path
CASINO_DB_PATH=/path/to/casino.db python migrations/migration_runner.py
```

## Creating a new migration

1. Create `migrations/00X_description.sql` (3-digit number, e.g. `002_add_heist_tables.sql`).
2. Use the format from `template.sql`: header comment, `-- UPGRADE` section, `-- DOWNGRADE` section.
3. Run `python migrations/migration_runner.py` to apply.
4. Commit the migration file with your code change.

## Naming convention

- `001_initial_schema.sql` — baseline
- `002_add_heist_tables.sql` — new tables
- `003_add_safe_balance.sql` — new column
- `004_add_user_nickname_index.sql` — new index

## Workflow when changing schema

1. Implement the feature that needs the schema change.
2. Add a new migration file (next version number).
3. Apply: `python migrations/migration_runner.py`.
4. Test the feature.
5. Commit migration + code together.

## Rollback

There is no automatic downgrade. To rollback:

1. Restore DB from backup: `cp casino.db.backup casino.db`
2. Or run the DOWNGRADE SQL from the migration file manually (if provided).

## Production

Before deploy:

1. Backup: `cp casino.db casino.db.backup`
2. Apply migrations: `python migrations/migration_runner.py`
3. On error, restore from backup and fix the migration.
