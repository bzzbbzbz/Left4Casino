"""Unit tests for automated backup service."""

import sqlite3
import stat
import tarfile
from os import utime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.backup import BackupResult, BackupService

pytestmark = pytest.mark.unit


def _create_sqlite_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, balance INTEGER)")
        connection.execute("INSERT INTO users (user_id, balance) VALUES (1, 50)")


def _make_service(tmp_path: Path, *, admin_id: int = 1, bot: MagicMock | None = None):
    db_path = tmp_path / "casino.db"
    settings_path = tmp_path / "settings.toml"
    groups_path = tmp_path / "groups.json"
    backup_dir = tmp_path / "backups"

    _create_sqlite_db(db_path)
    settings_path.write_text("[bot]\ntoken = 'test'\n", encoding="utf-8")
    groups_path.write_text("{}\n", encoding="utf-8")

    service = BackupService(
        db_path=db_path,
        settings_path=settings_path,
        groups_path=groups_path,
        backup_dir=backup_dir,
        retention_days=7,
        bot=bot,
        admin_id=admin_id,
        timezone_str="UTC",
    )
    return service, db_path, settings_path, groups_path, backup_dir


@pytest.mark.asyncio
async def test_create_backup_archive_contains_critical_files(tmp_path: Path) -> None:
    service, _, _, _, _ = _make_service(tmp_path)

    backup = await service.create_backup()

    assert isinstance(backup, BackupResult)
    assert backup.path.exists()
    assert backup.path.name.startswith("backup_")
    assert backup.path.name.endswith(".tar.gz")

    with tarfile.open(backup.path, "r:gz") as archive:
        names = set(archive.getnames())

    assert "bot/casino.db" in names
    assert "settings.toml" in names
    assert "groups.json" in names
    assert all(file.included for file in backup.files)


@pytest.mark.asyncio
async def test_create_backup_uses_private_permissions(tmp_path: Path) -> None:
    service, _, _, _, backup_dir = _make_service(tmp_path)

    backup = await service.create_backup()

    assert backup is not None
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_create_backup_preserves_sqlite_snapshot_integrity(tmp_path: Path) -> None:
    service, _, _, _, _ = _make_service(tmp_path)

    backup = await service.create_backup()

    assert backup is not None

    with tarfile.open(backup.path, "r:gz") as archive:
        archive.extract("bot/casino.db", path=tmp_path / "restore", filter="data")

    restored_db = tmp_path / "restore" / "bot" / "casino.db"
    with sqlite3.connect(restored_db) as connection:
        row = connection.execute("SELECT user_id, balance FROM users").fetchone()

    assert row == (1, 50)


@pytest.mark.asyncio
async def test_create_backup_skips_missing_plain_file(tmp_path: Path) -> None:
    service, _, settings_path, _, _ = _make_service(tmp_path)
    settings_path.unlink()

    backup = await service.create_backup()

    assert backup is not None
    missing = [file for file in backup.files if file.arcname == "settings.toml"]
    assert missing
    assert missing[0].included is False
    assert missing[0].reason == "not_found"

    with tarfile.open(backup.path, "r:gz") as archive:
        names = set(archive.getnames())

    assert "bot/casino.db" in names
    assert "settings.toml" not in names
    assert "groups.json" in names


@pytest.mark.asyncio
async def test_create_backup_skips_file_when_archive_add_fails(tmp_path: Path) -> None:
    service, _, _, _, _ = _make_service(tmp_path)
    original_add = tarfile.TarFile.add

    def add_with_groups_failure(self, name, arcname=None, *args, **kwargs):  # noqa: ANN001
        if arcname == "groups.json":
            raise OSError("cannot read groups")
        return original_add(self, name, arcname, *args, **kwargs)

    with patch.object(tarfile.TarFile, "add", add_with_groups_failure):
        backup = await service.create_backup()

    assert backup is not None
    groups_status = [file for file in backup.files if file.arcname == "groups.json"][0]
    assert groups_status.included is False
    assert groups_status.reason.startswith("archive_add_failed:")

    with tarfile.open(backup.path, "r:gz") as archive:
        names = set(archive.getnames())

    assert "bot/casino.db" in names
    assert "settings.toml" in names
    assert "groups.json" not in names


@pytest.mark.asyncio
async def test_create_backup_cleans_partial_archive_on_unexpected_failure(tmp_path: Path) -> None:
    service, _, _, _, backup_dir = _make_service(tmp_path)

    with patch.object(service, "_plain_files", side_effect=RuntimeError("boom")):
        backup = await service.create_backup()

    assert backup is None
    assert list(backup_dir.glob("backup_*.tar.gz")) == []
    assert list(backup_dir.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_create_backup_names_do_not_collide_within_same_second(tmp_path: Path) -> None:
    service, _, _, _, _ = _make_service(tmp_path)

    first = await service.create_backup()
    second = await service.create_backup()

    assert first is not None
    assert second is not None
    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()


@pytest.mark.asyncio
async def test_send_to_admin_sends_document_with_caption(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_document = AsyncMock()
    service, _, _, _, _ = _make_service(tmp_path, bot=bot, admin_id=123)
    backup = await service.create_backup()

    assert backup is not None
    sent = await service.send_to_admin(backup)

    assert sent is True
    bot.send_document.assert_awaited_once()
    call = bot.send_document.await_args.kwargs
    assert call["chat_id"] == 123
    assert "Ежедневный бэкап" in call["caption"]
    assert backup.path.name in call["caption"]


@pytest.mark.asyncio
async def test_send_to_admin_skips_when_admin_not_configured(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_document = AsyncMock()
    service, _, _, _, _ = _make_service(tmp_path, bot=bot, admin_id=0)
    backup = await service.create_backup()

    assert backup is not None
    sent = await service.send_to_admin(backup)

    assert sent is False
    bot.send_document.assert_not_called()


@pytest.mark.asyncio
async def test_send_to_admin_returns_false_when_telegram_send_fails(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_document = AsyncMock(side_effect=RuntimeError("telegram down"))
    service, _, _, _, _ = _make_service(tmp_path, bot=bot, admin_id=123)
    backup = await service.create_backup()

    assert backup is not None
    sent = await service.send_to_admin(backup)

    assert sent is False
    bot.send_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotate_old_backups_keeps_latest_archives(tmp_path: Path) -> None:
    service, _, _, _, backup_dir = _make_service(tmp_path)
    service.retention_days = 2
    backup_dir.mkdir(parents=True, exist_ok=True)

    old = backup_dir / "backup_20260101_000000.tar.gz"
    middle = backup_dir / "backup_20260102_000000.tar.gz"
    newest = backup_dir / "backup_20260103_000000.tar.gz"
    for index, path in enumerate((old, middle, newest), start=1):
        path.write_text("x", encoding="utf-8")
        utime(path, (index, index))

    removed = await service.rotate_old_backups()

    assert removed == 1
    assert not old.exists()
    assert middle.exists()
    assert newest.exists()
