"""Automated backup service for critical bot runtime files."""

import asyncio
import os
import sqlite3
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from aiogram import Bot
from aiogram.types import FSInputFile

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BackupFileStatus:
    """Status for a file that should be included in a backup archive."""

    arcname: str
    source_path: Path
    included: bool
    size_bytes: int = 0
    reason: str = ""


@dataclass(frozen=True)
class BackupResult:
    """Result of a completed backup archive creation."""

    path: Path
    created_at: datetime
    files: tuple[BackupFileStatus, ...]


class BackupService:
    """Create, send, and rotate daily backups."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        settings_path: str | Path | None,
        groups_path: str | Path,
        backup_dir: str | Path = "/tmp/casino_backups",
        retention_days: int = 7,
        bot: Bot | None = None,
        admin_id: int = 0,
        timezone_str: str = "UTC",
    ) -> None:
        self.db_path = Path(db_path)
        self.settings_path = Path(settings_path) if settings_path else None
        self.groups_path = Path(groups_path)
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days
        self.bot = bot
        self.admin_id = admin_id
        self.timezone = self._load_timezone(timezone_str)

    async def create_backup(self) -> BackupResult | None:
        """Create a tar.gz archive with critical runtime files."""
        try:
            return await asyncio.to_thread(self._create_backup_sync)
        except Exception as error:
            await logger.aerror("backup_create_failed", error=str(error))
            return None

    async def send_to_admin(self, backup: BackupResult | Path | str) -> bool:
        """Send a backup archive to the configured admin via Telegram."""
        if self.admin_id == 0 or self.bot is None:
            await logger.ainfo("backup_send_skipped", reason="admin_not_configured")
            return False

        backup_path = backup.path if isinstance(backup, BackupResult) else Path(backup)
        caption = self._build_caption(backup)

        try:
            await self.bot.send_document(
                chat_id=self.admin_id,
                document=FSInputFile(backup_path),
                caption=caption,
            )
        except Exception as error:
            await logger.aerror(
                "backup_send_failed",
                path=str(backup_path),
                admin_id=self.admin_id,
                error=str(error),
            )
            return False

        await logger.ainfo("backup_sent", path=str(backup_path), admin_id=self.admin_id)
        return True

    async def rotate_old_backups(self) -> int:
        """Remove old backup archives, keeping only the latest configured count."""
        try:
            return await asyncio.to_thread(self._rotate_old_backups_sync)
        except Exception as error:
            await logger.aerror("backup_rotation_failed", error=str(error))
            return 0

    async def run_backup(self) -> None:
        """Run full backup workflow: create, send, rotate."""
        backup = await self.create_backup()
        if backup is None:
            return
        await self.send_to_admin(backup)
        await self.rotate_old_backups()

    def _create_backup_sync(self) -> BackupResult:
        self._ensure_secure_backup_dir()
        created_at = datetime.now(self.timezone)
        backup_path = self._new_backup_path(created_at)
        temp_backup_path = self.backup_dir / f".{backup_path.name}.{uuid.uuid4().hex}.tmp"
        files: list[BackupFileStatus] = []

        try:
            with tempfile.TemporaryDirectory(
                prefix="backup_work_", dir=self.backup_dir
            ) as temp_dir:
                temp_path = Path(temp_dir)
                db_snapshot = temp_path / "casino.db"

                with self._open_secure_tar(temp_backup_path) as archive:
                    db_status = self._snapshot_sqlite_db(db_snapshot)
                    if db_status.included:
                        db_status = self._add_file_to_archive(
                            archive,
                            source_path=db_snapshot,
                            arcname=db_status.arcname,
                            reported_source_path=self.db_path,
                        )
                    files.append(db_status)

                    for source_path, arcname in self._plain_files():
                        status = self._add_file_to_archive(
                            archive,
                            source_path=source_path,
                            arcname=arcname,
                        )
                        files.append(status)

            temp_backup_path.replace(backup_path)
        except Exception:
            temp_backup_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)
            raise

        return BackupResult(path=backup_path, created_at=created_at, files=tuple(files))

    def _ensure_secure_backup_dir(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backup_dir.chmod(0o700)

    def _new_backup_path(self, created_at: datetime) -> Path:
        for _ in range(100):
            candidate = self.backup_dir / f"backup_{created_at:%Y%m%d_%H%M%S_%f}.tar.gz"
            if not candidate.exists():
                return candidate
            created_at = datetime.now(self.timezone)
        return self.backup_dir / f"backup_{created_at:%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex}.tar.gz"

    def _open_secure_tar(self, temp_backup_path: Path) -> tarfile.TarFile:
        fd = os.open(
            temp_backup_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            fileobj = os.fdopen(fd, "wb")
        except Exception:
            os.close(fd)
            raise
        try:
            return tarfile.open(fileobj=fileobj, mode="w:gz")
        except Exception:
            fileobj.close()
            raise

    def _snapshot_sqlite_db(self, snapshot_path: Path) -> BackupFileStatus:
        arcname = "bot/casino.db"
        if not self.db_path.exists():
            return BackupFileStatus(
                arcname=arcname,
                source_path=self.db_path,
                included=False,
                reason="not_found",
            )

        try:
            with sqlite3.connect(self.db_path) as source:
                with sqlite3.connect(snapshot_path) as destination:
                    source.backup(destination)
        except Exception as error:
            return BackupFileStatus(
                arcname=arcname,
                source_path=self.db_path,
                included=False,
                reason=f"sqlite_backup_failed: {error}",
            )

        return BackupFileStatus(
            arcname=arcname,
            source_path=self.db_path,
            included=True,
            size_bytes=snapshot_path.stat().st_size,
        )

    def _plain_files(self) -> tuple[tuple[Path, str], ...]:
        files: list[tuple[Path, str]] = []
        if self.settings_path is not None:
            files.append((self.settings_path, "settings.toml"))
        files.append((self.groups_path, "groups.json"))
        return tuple(files)

    def _add_file_to_archive(
        self,
        archive: tarfile.TarFile,
        *,
        source_path: Path,
        arcname: str,
        reported_source_path: Path | None = None,
    ) -> BackupFileStatus:
        status_source_path = reported_source_path or source_path
        if not source_path.exists():
            return BackupFileStatus(
                arcname=arcname,
                source_path=status_source_path,
                included=False,
                reason="not_found",
            )

        try:
            size_bytes = source_path.stat().st_size
            archive.add(source_path, arcname=arcname)
        except Exception as error:
            return BackupFileStatus(
                arcname=arcname,
                source_path=status_source_path,
                included=False,
                reason=f"archive_add_failed: {error}",
            )

        return BackupFileStatus(
            arcname=arcname,
            source_path=status_source_path,
            included=True,
            size_bytes=size_bytes,
        )

    def _rotate_old_backups_sync(self) -> int:
        self._ensure_secure_backup_dir()
        backups = sorted(
            self.backup_dir.glob("backup_*.tar.gz"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        keep_count = max(1, self.retention_days)
        removed = 0
        for backup_path in backups[keep_count:]:
            backup_path.unlink(missing_ok=True)
            removed += 1
        return removed

    def _build_caption(self, backup: BackupResult | Path | str) -> str:
        if not isinstance(backup, BackupResult):
            backup_path = Path(backup)
            return f"📦 Ежедневный бэкап\n\n💾 Архив: {backup_path.name}"

        lines = [
            "📦 Ежедневный бэкап",
            "",
            f"🗓 Дата: {backup.created_at:%d.%m.%Y %H:%M:%S}",
            f"📊 Размер: {self._format_size(backup.path.stat().st_size)}",
            "📁 Файлы:",
        ]
        for file_status in backup.files:
            if file_status.included:
                lines.append(
                    f"✅ {file_status.arcname} ({self._format_size(file_status.size_bytes)})"
                )
            else:
                lines.append(f"⚠️ {file_status.arcname} ({file_status.reason or 'skipped'})")
        lines.extend(["", f"💾 Архив: {backup.path.name}"])
        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    @staticmethod
    def _load_timezone(timezone_str: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_str)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
