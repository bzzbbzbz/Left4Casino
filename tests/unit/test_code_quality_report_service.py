"""Unit tests for daily code-quality report service."""

import stat
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import CodeQualityReportConfig
from bot.services.code_quality_report import TELEGRAM_MESSAGE_LIMIT, CodeQualityReportService

pytestmark = pytest.mark.unit


def _make_config(tmp_path: Path, **overrides) -> CodeQualityReportConfig:
    data = {
        "output_dir": str(tmp_path / "reports"),
        "container_name": "python-runner",
        "log_since": "2026-02-16T15:40:00",
        "log_until": "2026-02-16T17:27:00",
        "grep_pattern": "warning|error|exception",
        "max_log_bytes": 4096,
        "max_artifact_bytes": 12000,
        "opencode_timeout_seconds": 5,
    }
    data.update(overrides)
    return CodeQualityReportConfig.model_validate(data)


def _make_service(tmp_path: Path, **overrides) -> CodeQualityReportService:
    return CodeQualityReportService(
        config=_make_config(tmp_path, **overrides),
        project_root=tmp_path,
        timezone_str="UTC",
    )


@pytest.mark.asyncio
async def test_since_until_filter_command_has_no_shell_and_redacts(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):  # noqa: ANN001
        calls.append(args)
        assert kwargs["capture_output"] is True
        assert "shell" not in kwargs or kwargs["shell"] is False
        if args[0] == "docker":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=b"INFO ok\nERROR token=SECRET123 /credit failed\nwarning noisy\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"Finding: token=SECRET123 should be hidden",
            stderr=b"",
        )

    with patch("bot.services.code_quality_report.shutil.which", return_value="/usr/bin/tool"):
        with patch("bot.services.code_quality_report.subprocess.run", side_effect=fake_run):
            result = await service.run_report()

    assert result is not None
    docker_call = calls[0]
    assert docker_call[:7] == [
        "docker",
        "logs",
        "--since",
        "2026-02-16T15:40:00+00:00",
        "--until",
        "2026-02-16T17:27:00+00:00",
        "--tail",
    ]
    assert docker_call[-1] == "python-runner"
    assert calls[1][0:2] == ["opencode", "run"]
    assert stat.S_IMODE(Path(service.config.output_dir).stat().st_mode) == 0o700
    assert stat.S_IMODE(result.summary_path.stat().st_mode) == 0o600
    logs_text = result.logs_path.read_text(encoding="utf-8")
    assert "INFO ok" not in logs_text
    assert "warning noisy" in logs_text
    assert "SECRET123" not in logs_text
    assert "[REDACTED]" in logs_text


@pytest.mark.asyncio
async def test_request_logs_second_pass_fetches_extra_logs_without_filter(tmp_path: Path) -> None:
    service = _make_service(tmp_path, max_extra_log_requests=1, max_extra_log_bytes=2000)
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):  # noqa: ANN001, ARG001
        calls.append(args)
        if args[0] == "docker" and len([call for call in calls if call[0] == "docker"]) == 1:
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"ERROR first\n", stderr=b""
            )
        if args[0] == "docker":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=b"INFO full context\nDEBUG still included\n",
                stderr=b"",
            )
        opencode_calls = [call for call in calls if call[0] == "opencode"]
        if len(opencode_calls) == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=b"REQUEST_LOGS: 2026-02-16T15:40:00+00:00 2026-02-16T15:45:00+00:00\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=b"final report", stderr=b""
        )

    with patch("bot.services.code_quality_report.shutil.which", return_value="/usr/bin/tool"):
        with patch("bot.services.code_quality_report.subprocess.run", side_effect=fake_run):
            result = await service.run_report()

    assert result is not None
    docker_calls = [call for call in calls if call[0] == "docker"]
    opencode_calls = [call for call in calls if call[0] == "opencode"]
    assert len(docker_calls) == 2
    assert len(opencode_calls) == 2
    assert "INFO full context" in opencode_calls[1][2]
    assert "DEBUG still included" in opencode_calls[1][2]
    assert result.opencode_path.read_text(encoding="utf-8") == "final report"


@pytest.mark.asyncio
async def test_nonzero_opencode_fallback_includes_safe_raw_logs(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    def fake_run(args, **kwargs):  # noqa: ANN001, ARG001
        if args[0] == "docker":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=b"ERROR token=SECRET123 bad runtime\n",
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=args, returncode=2, stdout=b"opencode failed", stderr=b""
        )

    with patch("bot.services.code_quality_report.shutil.which", return_value="/usr/bin/tool"):
        with patch("bot.services.code_quality_report.subprocess.run", side_effect=fake_run):
            result = await service.run_report()

    assert result is not None
    assert result.opencode_status == "opencode_exit_2"
    assert "AI-анализ не выполнен" in result.report_text
    assert "bad runtime" in result.report_text
    assert "SECRET123" not in result.report_text


@pytest.mark.asyncio
async def test_missing_opencode_fallback_includes_raw_tail(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    def fake_which(binary: str) -> str | None:
        return "/usr/bin/docker" if binary == "docker" else None

    with patch("bot.services.code_quality_report.shutil.which", side_effect=fake_which):
        with patch("bot.services.code_quality_report.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["docker"], returncode=0, stdout=b"ERROR raw fallback\n", stderr=b""
            )
            result = await service.run_report()

    assert result is not None
    assert result.opencode_status == "opencode_not_available"
    assert "ERROR raw fallback" in result.report_text


@pytest.mark.asyncio
async def test_telegram_send_message_chunks_and_truncates(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    service = CodeQualityReportService(
        config=_make_config(tmp_path),
        project_root=tmp_path,
        bot=bot,
        admin_id=123,
    )

    sent = await service._send_to_admin("x" * (TELEGRAM_MESSAGE_LIMIT * 5))

    assert sent is True
    assert bot.send_message.await_count == 4
    for call in bot.send_message.await_args_list:
        assert call.kwargs["chat_id"] == 123
        assert len(call.kwargs["text"]) <= TELEGRAM_MESSAGE_LIMIT
    assert "обрезано" in bot.send_message.await_args_list[-1].kwargs["text"]


@pytest.mark.asyncio
async def test_telegram_send_is_graceful(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    service = CodeQualityReportService(
        config=_make_config(tmp_path),
        project_root=tmp_path,
        bot=bot,
        admin_id=123,
    )

    with patch("bot.services.code_quality_report.shutil.which", return_value=None):
        result = await service.run_report()

    assert result is not None
    assert result.sent_to_telegram is False
    bot.send_message.assert_awaited_once()
