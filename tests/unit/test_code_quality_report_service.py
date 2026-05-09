"""Unit tests for daily code-quality report service."""

import stat
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config_reader import CodeQualityReportConfig
from bot.services.code_quality_report import CodeQualityReportService

pytestmark = pytest.mark.unit


def _make_config(tmp_path: Path, **overrides) -> CodeQualityReportConfig:
    data = {
        "output_dir": str(tmp_path / "reports"),
        "container_name": "python-runner",
        "max_log_bytes": 4096,
        "max_artifact_bytes": 8192,
        "opencode_timeout_seconds": 5,
    }
    data.update(overrides)
    return CodeQualityReportConfig.model_validate(data)


def _make_service(tmp_path: Path, **overrides) -> CodeQualityReportService:
    return CodeQualityReportService(
        config=_make_config(tmp_path, **overrides),
        project_root=tmp_path,
        timezone_str="UTC",
        request_logs_env="ERROR,/credit",
    )


@pytest.mark.asyncio
async def test_run_report_uses_docker_and_opencode_without_shell_and_redacts(
    tmp_path: Path,
) -> None:
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
                stdout=b"INFO ok\nERROR token=SECRET123 /credit failed\n",
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
    assert calls[0][:4] == ["docker", "logs", "--tail", "1000"]
    assert calls[0][4] == "python-runner"
    assert calls[1][0:2] == ["opencode", "run"]
    assert stat.S_IMODE(Path(service.config.output_dir).stat().st_mode) == 0o700
    assert stat.S_IMODE(result.summary_path.stat().st_mode) == 0o600
    assert "SECRET123" not in result.summary_path.read_text(encoding="utf-8")
    assert "SECRET123" not in result.logs_path.read_text(encoding="utf-8")
    assert "[REDACTED]" in result.logs_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_run_report_falls_back_when_docker_and_opencode_missing(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    with patch("bot.services.code_quality_report.shutil.which", return_value=None):
        result = await service.run_report()

    assert result is not None
    assert result.docker_status == "docker_not_available"
    assert result.opencode_status == "opencode_not_available"
    assert "fallback" in result.opencode_path.read_text(encoding="utf-8")


def test_request_logs_parser_caps_and_escapes_invalid_patterns(tmp_path: Path) -> None:
    raw = "ERROR,(invalid,[too-long]" + "x" * 300 + ",ignored"
    service = CodeQualityReportService(
        config=_make_config(
            tmp_path,
            request_logs_max_patterns=2,
            request_logs_max_pattern_length=20,
            request_logs_max_matches=1,
        ),
        project_root=tmp_path,
        request_logs_env=raw,
    )

    filtered = service._filter_request_logs("INFO ok\nERROR one\nERROR two\n")

    assert filtered == "ERROR one"
    assert len(service._parse_request_logs_patterns()) == 2


@pytest.mark.asyncio
async def test_telegram_send_is_graceful(tmp_path: Path) -> None:
    bot = MagicMock()
    bot.send_document = AsyncMock(side_effect=RuntimeError("telegram down"))
    service = CodeQualityReportService(
        config=_make_config(tmp_path),
        project_root=tmp_path,
        bot=bot,
        admin_id=123,
        request_logs_env="ERROR",
    )

    with patch("bot.services.code_quality_report.shutil.which", return_value=None):
        result = await service.run_report()

    assert result is not None
    assert result.sent_to_telegram is False
    bot.send_document.assert_awaited_once()
