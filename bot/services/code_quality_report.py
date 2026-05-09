"""Daily code-quality report service built from Docker logs and OpenCode analysis."""

import asyncio
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from aiogram import Bot

from bot.config_reader import CodeQualityReportConfig

logger = structlog.get_logger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
TRUNCATION_MARK = "\n… (обрезано)"
REQUEST_LOGS_RE = re.compile(r"^\s*REQUEST_LOGS:\s+(\S+)\s+(\S+)\s*$", re.MULTILINE)
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
    """Created report artifacts and delivery status."""

    summary_path: Path
    logs_path: Path
    opencode_path: Path
    sent_to_telegram: bool
    docker_status: str
    opencode_status: str
    report_text: str


class CodeQualityReportService:
    """Collect filtered Docker logs, optionally expand context, and report to admin."""

    def __init__(
        self,
        *,
        config: CodeQualityReportConfig,
        project_root: Path,
        bot: Bot | None = None,
        admin_id: int = 0,
        timezone_str: str = "UTC",
    ) -> None:
        self.config = config
        self.project_root = project_root
        self.bot = bot
        self.admin_id = admin_id
        self.timezone = self._load_timezone(timezone_str)

    async def run_report(self) -> CodeQualityReportResult | None:
        """Run report workflow without raising on Docker/OpenCode/Telegram failures."""
        try:
            result = await asyncio.to_thread(self._create_report_sync)
        except Exception as error:
            await logger.aerror("code_quality_report_failed", error=str(error))
            return None

        sent = await self._send_to_admin(result.report_text)
        return CodeQualityReportResult(
            summary_path=result.summary_path,
            logs_path=result.logs_path,
            opencode_path=result.opencode_path,
            sent_to_telegram=sent,
            docker_status=result.docker_status,
            opencode_status=result.opencode_status,
            report_text=result.report_text,
        )

    def _create_report_sync(self) -> CodeQualityReportResult:
        self._ensure_secure_output_dir()
        created_at = datetime.now(self.timezone)
        stem = f"code_quality_{created_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"

        log_since, log_until = self._resolve_log_window(created_at)
        docker_result = self._collect_docker_logs(
            since=log_since, until=log_until, apply_filter=True
        )
        safe_filtered_logs = self._redact(docker_result.output)

        logs_text = (
            f"Docker status: {'ok' if docker_result.ok else docker_result.reason}\n"
            f"Container: {self.config.container_name}\n"
            f"Window: {log_since} — {log_until}\n"
            f"Filter: {self.config.grep_pattern}\n\n"
            f"## Filtered docker logs (redacted, capped)\n{safe_filtered_logs or '(empty)'}\n"
        )
        logs_path = self._write_secure_text(f"{stem}.logs.txt", logs_text)

        opencode_result, combined_context = self._run_opencode_workflow(
            safe_filtered_logs=safe_filtered_logs,
            primary_window=(log_since, log_until),
        )
        safe_opencode = self._redact(opencode_result.output)
        opencode_path = self._write_secure_text(f"{stem}.opencode.md", safe_opencode)

        report_text = self._build_admin_report(
            created_at=created_at,
            docker_result=docker_result,
            opencode_result=CommandResult(
                ok=opencode_result.ok, output=safe_opencode, reason=opencode_result.reason
            ),
            combined_context=combined_context,
            logs_path=logs_path,
            opencode_path=opencode_path,
        )
        summary_path = self._write_secure_text(f"{stem}.summary.md", report_text)

        return CodeQualityReportResult(
            summary_path=summary_path,
            logs_path=logs_path,
            opencode_path=opencode_path,
            sent_to_telegram=False,
            docker_status="ok" if docker_result.ok else docker_result.reason,
            opencode_status="ok" if opencode_result.ok else opencode_result.reason,
            report_text=report_text,
        )

    def _collect_docker_logs(self, *, since: str, until: str, apply_filter: bool) -> CommandResult:
        if shutil.which("docker") is None:
            return CommandResult(ok=False, output="", reason="docker_not_available")

        args = [
            "docker",
            "logs",
            "--since",
            since,
            "--until",
            until,
            "--tail",
            str(self.config.docker_tail_lines),
            self.config.container_name,
        ]
        try:
            completed = subprocess.run(
                args,
                cwd=self.project_root,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(ok=False, output="", reason="docker_timeout")
        except OSError as error:
            return CommandResult(ok=False, output="", reason=f"docker_error: {error}")

        output = (completed.stdout + completed.stderr)[: self.config.max_log_bytes].decode(
            "utf-8", errors="replace"
        )
        if apply_filter:
            output = self._filter_logs(output)
        if completed.returncode != 0:
            return CommandResult(
                ok=False, output=output, reason=f"docker_exit_{completed.returncode}"
            )
        return CommandResult(ok=True, output=output)

    def _run_opencode_workflow(
        self, *, safe_filtered_logs: str, primary_window: tuple[str, str]
    ) -> tuple[CommandResult, str]:
        first_context = self._build_context(
            filtered_logs=safe_filtered_logs,
            extra_logs="",
            primary_window=primary_window,
        )
        first_result = self._run_opencode(first_context)
        if not first_result.ok:
            return first_result, first_context

        requests = self._parse_request_logs(first_result.output)
        if not requests:
            return first_result, first_context

        extra_logs = self._fetch_extra_logs(requests)
        combined_context = self._build_context(
            filtered_logs=safe_filtered_logs,
            extra_logs=extra_logs,
            primary_window=primary_window,
        )
        second_result = self._run_opencode(combined_context)
        return second_result, combined_context

    def _run_opencode(self, context: str) -> CommandResult:
        if shutil.which("opencode") is None:
            return CommandResult(ok=False, output="", reason="opencode_not_available")

        prompt = self._build_opencode_prompt(context)
        try:
            completed = subprocess.run(
                ["opencode", "run", prompt],
                cwd=self.project_root,
                capture_output=True,
                check=False,
                timeout=self.config.opencode_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(ok=False, output="", reason="opencode_timeout")
        except OSError as error:
            return CommandResult(ok=False, output="", reason=f"opencode_error: {error}")

        output = (completed.stdout + completed.stderr)[: self.config.max_artifact_bytes].decode(
            "utf-8", errors="replace"
        )
        if completed.returncode != 0:
            return CommandResult(
                ok=False, output=output, reason=f"opencode_exit_{completed.returncode}"
            )
        return CommandResult(ok=True, output=output)

    def _fetch_extra_logs(self, requests: tuple[tuple[str, str], ...]) -> str:
        chunks: list[str] = []
        used_bytes = 0
        for since, until in requests[: self.config.max_extra_log_requests]:
            remaining = self.config.max_extra_log_bytes - used_bytes
            if remaining <= 0:
                break
            result = self._collect_docker_logs(since=since, until=until, apply_filter=False)
            header = f"\n## REQUEST_LOGS {since} {until} ({'ok' if result.ok else result.reason})\n"
            chunk = self._redact(result.output)[:remaining]
            text = header + chunk
            used_bytes += len(text.encode("utf-8"))
            chunks.append(text)
        return "\n".join(chunks)[: self.config.max_extra_log_bytes]

    def _filter_logs(self, logs: str) -> str:
        pattern = re.compile(self.config.grep_pattern, re.IGNORECASE)
        matches = [line for line in logs.splitlines() if pattern.search(line)]
        return "\n".join(matches)[: self.config.max_log_bytes]

    def _parse_request_logs(self, output: str) -> tuple[tuple[str, str], ...]:
        requests: list[tuple[str, str]] = []
        for match in REQUEST_LOGS_RE.finditer(output):
            requests.append((match.group(1), match.group(2)))
            if len(requests) >= self.config.max_extra_log_requests:
                break
        return tuple(requests)

    def _build_context(
        self, *, filtered_logs: str, extra_logs: str, primary_window: tuple[str, str]
    ) -> str:
        since, until = primary_window
        return self._redact(
            f"Primary window: {since} — {until}\n"
            f"Filter: {self.config.grep_pattern}\n\n"
            "## Filtered Docker logs\n"
            f"{filtered_logs or '(empty)'}\n\n"
            "## Extra unfiltered Docker logs requested by OpenCode\n"
            f"{extra_logs or '(none)'}\n"
        )[: self.config.max_artifact_bytes]

    def _build_opencode_prompt(self, context: str) -> str:
        return self._redact(
            "Проанализируй runtime-логи Telegram casino bot. "
            "Если для полной картины нужен неотфильтрованный интервал, выведи строки "
            "REQUEST_LOGS: <since_iso> <until_iso>. Если контекста хватает, дай итоговый "
            "краткий отчёт на русском: количество совпадений, серьёзность, вероятная зона кода, "
            "рекомендации. Не включай секреты.\n\n"
            f"{context}"
        )[: self.config.max_artifact_bytes]

    def _build_admin_report(
        self,
        *,
        created_at: datetime,
        docker_result: CommandResult,
        opencode_result: CommandResult,
        combined_context: str,
        logs_path: Path,
        opencode_path: Path,
    ) -> str:
        raw_tail = self._safe_tail(combined_context, 1800)
        if opencode_result.ok:
            analysis = opencode_result.output or "OpenCode вернул пустой ответ."
        else:
            analysis = (
                f"AI-анализ не выполнен: {opencode_result.reason}. "
                "Ниже безопасный хвост сырых логов."
            )

        return self._redact(
            "🧪 Ежедневный отчёт качества кода\n"
            f"Создан: {created_at.isoformat()}\n"
            f"Docker: {'ok' if docker_result.ok else docker_result.reason}\n"
            f"OpenCode: {'ok' if opencode_result.ok else opencode_result.reason}\n"
            f"Артефакты: {logs_path.name}, {opencode_path.name}\n\n"
            "## Анализ\n"
            f"{analysis}\n\n"
            "## Безопасный хвост логов\n"
            f"{raw_tail or '(empty)'}\n"
        )[: self.config.max_artifact_bytes]

    async def _send_to_admin(self, report_text: str) -> bool:
        if self.admin_id == 0 or self.bot is None:
            await logger.ainfo("code_quality_report_send_skipped", reason="admin_not_configured")
            return False

        try:
            for chunk in self._split_telegram_messages(report_text):
                await self.bot.send_message(chat_id=self.admin_id, text=chunk)
        except Exception as error:
            await logger.aerror("code_quality_report_send_failed", error=str(error))
            return False
        return True

    def _split_telegram_messages(self, text: str) -> tuple[str, ...]:
        max_messages = 4
        chunks: list[str] = []
        remaining = text
        while remaining and len(chunks) < max_messages:
            chunk = remaining[:TELEGRAM_MESSAGE_LIMIT]
            remaining = remaining[TELEGRAM_MESSAGE_LIMIT:]
            if remaining and len(chunks) == max_messages - 1:
                available = TELEGRAM_MESSAGE_LIMIT - len(TRUNCATION_MARK)
                chunk = chunk[:available] + TRUNCATION_MARK
                remaining = ""
            chunks.append(chunk)
        return tuple(chunks or ["(empty report)"])

    def _resolve_log_window(self, now: datetime) -> tuple[str, str]:
        since_dt = self._parse_time_value(self.config.log_since, now)
        until_dt = self._parse_time_value(self.config.log_until, now)
        return since_dt.isoformat(), until_dt.isoformat()

    def _parse_time_value(self, value: str, now: datetime) -> datetime:
        normalized = value.strip().lower()
        if normalized == "now":
            return now
        relative = re.fullmatch(r"(\d+)([hm])", normalized)
        if relative:
            amount = int(relative.group(1))
            delta = (
                timedelta(hours=amount) if relative.group(2) == "h" else timedelta(minutes=amount)
            )
            return now - delta

        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.timezone)
        return parsed

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

    def _safe_tail(self, value: str, max_chars: int) -> str:
        return self._redact(value[-max_chars:])

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
