"""Daily code-quality report service built from runtime logs and OpenCode analysis."""

import asyncio
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from aiogram import Bot
from aiogram.types import FSInputFile

from bot.config_reader import CodeQualityReportConfig

logger = structlog.get_logger(__name__)

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|sk-or-v1)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[=:]\s*['\"]?[^\s'\"]+"),
)


@dataclass(frozen=True)
class CommandResult:
    """Captured command execution with graceful failure state."""

    ok: bool
    output: str
    reason: str = ""


@dataclass(frozen=True)
class CodeQualityReportResult:
    """Created report artifact locations and delivery status."""

    summary_path: Path
    logs_path: Path
    opencode_path: Path
    sent_to_telegram: bool
    docker_status: str
    opencode_status: str


class CodeQualityReportService:
    """Collect Docker logs, request-log slices, and optional OpenCode analysis."""

    def __init__(
        self,
        *,
        config: CodeQualityReportConfig,
        project_root: Path,
        bot: Bot | None = None,
        admin_id: int = 0,
        timezone_str: str = "UTC",
        request_logs_env: str | None = None,
    ) -> None:
        self.config = config
        self.project_root = project_root
        self.bot = bot
        self.admin_id = admin_id
        self.timezone = self._load_timezone(timezone_str)
        self.request_logs_env = request_logs_env

    async def run_report(self) -> CodeQualityReportResult | None:
        """Run the full report workflow without raising on external-tool failures."""
        try:
            result = await asyncio.to_thread(self._create_report_sync)
        except Exception as error:
            await logger.aerror("code_quality_report_failed", error=str(error))
            return None

        sent = await self._send_to_admin(result.summary_path)
        return CodeQualityReportResult(
            summary_path=result.summary_path,
            logs_path=result.logs_path,
            opencode_path=result.opencode_path,
            sent_to_telegram=sent,
            docker_status=result.docker_status,
            opencode_status=result.opencode_status,
        )

    def _create_report_sync(self) -> CodeQualityReportResult:
        self._ensure_secure_output_dir()
        created_at = datetime.now(self.timezone)
        stem = f"code_quality_{created_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"

        docker_result = self._collect_docker_logs()
        redacted_logs = self._redact(docker_result.output)
        filtered_logs = self._filter_request_logs(redacted_logs)

        logs_text = (
            f"Docker status: {'ok' if docker_result.ok else docker_result.reason}\n"
            f"Container: {self.config.container_name}\n\n"
            f"## Filtered REQUEST_LOGS matches\n{filtered_logs or '(none)'}\n\n"
            f"## Raw docker logs (redacted, capped)\n{redacted_logs or '(empty)'}\n"
        )
        logs_path = self._write_secure_text(f"{stem}.logs.txt", logs_text)

        opencode_result = self._run_opencode_analysis(redacted_logs, filtered_logs)
        opencode_text = self._redact(opencode_result.output)
        opencode_path = self._write_secure_text(f"{stem}.opencode.md", opencode_text)

        summary_text = self._build_summary(
            created_at=created_at,
            docker_result=docker_result,
            opencode_result=opencode_result,
            logs_path=logs_path,
            opencode_path=opencode_path,
        )
        summary_path = self._write_secure_text(f"{stem}.summary.md", self._redact(summary_text))

        return CodeQualityReportResult(
            summary_path=summary_path,
            logs_path=logs_path,
            opencode_path=opencode_path,
            sent_to_telegram=False,
            docker_status="ok" if docker_result.ok else docker_result.reason,
            opencode_status="ok" if opencode_result.ok else opencode_result.reason,
        )

    def _collect_docker_logs(self) -> CommandResult:
        if shutil.which("docker") is None:
            return CommandResult(ok=False, output="", reason="docker_not_available")

        try:
            completed = subprocess.run(
                [
                    "docker",
                    "logs",
                    "--tail",
                    str(self.config.docker_tail_lines),
                    self.config.container_name,
                ],
                cwd=self.project_root,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(ok=False, output="", reason="docker_timeout")
        except OSError as error:
            return CommandResult(ok=False, output="", reason=f"docker_error: {error}")

        output_bytes = completed.stdout + completed.stderr
        output = output_bytes[: self.config.max_log_bytes].decode("utf-8", errors="replace")
        if completed.returncode != 0:
            return CommandResult(
                ok=False, output=output, reason=f"docker_exit_{completed.returncode}"
            )
        return CommandResult(ok=True, output=output)

    def _run_opencode_analysis(self, logs: str, filtered_logs: str) -> CommandResult:
        if shutil.which("opencode") is None:
            return CommandResult(
                ok=False,
                output=self._fallback_analysis(logs, filtered_logs),
                reason="opencode_not_available",
            )

        prompt = self._build_opencode_prompt(logs, filtered_logs)
        try:
            completed = subprocess.run(
                ["opencode", "run", prompt],
                cwd=self.project_root,
                capture_output=True,
                check=False,
                timeout=self.config.opencode_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                ok=False,
                output=self._fallback_analysis(logs, filtered_logs),
                reason="opencode_timeout",
            )
        except OSError as error:
            return CommandResult(
                ok=False,
                output=self._fallback_analysis(logs, filtered_logs),
                reason=f"opencode_error: {error}",
            )

        output = (completed.stdout + completed.stderr)[: self.config.max_artifact_bytes].decode(
            "utf-8", errors="replace"
        )
        if completed.returncode != 0:
            return CommandResult(
                ok=False, output=output, reason=f"opencode_exit_{completed.returncode}"
            )
        return CommandResult(ok=True, output=output)

    def _build_opencode_prompt(self, logs: str, filtered_logs: str) -> str:
        capped_logs = logs[: self.config.max_log_bytes]
        capped_filtered = filtered_logs[: self.config.max_log_bytes]
        return self._redact(
            "Review the Telegram casino bot runtime logs for code-quality issues. "
            "Return concise findings grouped by severity, likely source area, and suggested fix. "
            "Do not include secrets.\n\n"
            f"REQUEST_LOGS matches:\n{capped_filtered}\n\nDocker logs:\n{capped_logs}"
        )

    def _fallback_analysis(self, logs: str, filtered_logs: str) -> str:
        error_lines = [
            line
            for line in logs.splitlines()
            if re.search(r"(?i)error|exception|traceback|failed", line)
        ][:50]
        return (
            "# Code Quality Report (fallback)\n\n"
            "OpenCode was unavailable or failed, so this report uses local regex analysis.\n\n"
            f"- REQUEST_LOGS matches: {len(filtered_logs.splitlines()) if filtered_logs else 0}\n"
            f"- Error-like log lines: {len(error_lines)}\n\n"
            "## Error-like lines\n"
            + ("\n".join(error_lines) if error_lines else "None detected")
            + "\n"
        )

    def _filter_request_logs(self, logs: str) -> str:
        patterns = self._parse_request_logs_patterns()
        if not patterns:
            return ""

        matches: list[str] = []
        for line in logs.splitlines():
            if len(matches) >= self.config.request_logs_max_matches:
                break
            if any(pattern.search(line) for pattern in patterns):
                matches.append(line)
        return "\n".join(matches)[: self.config.max_log_bytes]

    def _parse_request_logs_patterns(self) -> tuple[re.Pattern[str], ...]:
        raw = (
            self.request_logs_env
            if self.request_logs_env is not None
            else os.getenv("REQUEST_LOGS", "")
        )
        if not raw:
            return ()

        compiled: list[re.Pattern[str]] = []
        tokens = re.split(r"[\n,]", raw)
        for token in tokens[: self.config.request_logs_max_patterns]:
            pattern_text = token.strip()
            if not pattern_text:
                continue
            pattern_text = pattern_text[: self.config.request_logs_max_pattern_length]
            try:
                compiled.append(re.compile(pattern_text))
            except re.error:
                compiled.append(re.compile(re.escape(pattern_text)))
        return tuple(compiled)

    def _build_summary(
        self,
        *,
        created_at: datetime,
        docker_result: CommandResult,
        opencode_result: CommandResult,
        logs_path: Path,
        opencode_path: Path,
    ) -> str:
        return (
            "# Daily Code Quality Report\n\n"
            f"Created: {created_at.isoformat()}\n"
            f"Docker: {'ok' if docker_result.ok else docker_result.reason}\n"
            f"OpenCode: {'ok' if opencode_result.ok else opencode_result.reason}\n"
            f"Logs artifact: {logs_path}\n"
            f"OpenCode artifact: {opencode_path}\n\n"
            "## Analysis\n\n"
            f"{opencode_result.output[: self.config.max_artifact_bytes]}\n"
        )

    async def _send_to_admin(self, summary_path: Path) -> bool:
        if self.admin_id == 0 or self.bot is None:
            await logger.ainfo("code_quality_report_send_skipped", reason="admin_not_configured")
            return False

        try:
            await self.bot.send_document(
                chat_id=self.admin_id,
                document=FSInputFile(summary_path),
                caption="Ежедневный отчёт качества кода",
            )
        except Exception as error:
            await logger.aerror("code_quality_report_send_failed", error=str(error))
            return False
        return True

    def _ensure_secure_output_dir(self) -> None:
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        output_dir.chmod(0o700)

    def _write_secure_text(self, filename: str, text: str) -> Path:
        output_dir = Path(self.config.output_dir)
        path = output_dir / filename
        data = text[: self.config.max_artifact_bytes].encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
        except Exception:
            os.close(fd)
            raise
        path.chmod(0o600)
        return path

    def _redact(self, value: str) -> str:
        redacted = value
        for pattern in SECRET_PATTERNS:
            if pattern.pattern.startswith("(?i)\\b(bearer"):
                redacted = pattern.sub(r"\1[REDACTED]", redacted)
            elif "api" in pattern.pattern.lower() or "token" in pattern.pattern.lower():
                redacted = pattern.sub(r"\1=[REDACTED]", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    @staticmethod
    def _load_timezone(timezone_str: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_str)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
