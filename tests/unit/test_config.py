"""Unit tests for config loading and startup-critical GameConfig usage."""

from unittest.mock import patch

import pytest

from bot.config_reader import BackupsConfig, CodeQualityReportConfig, GameConfig, get_config
from bot.middlewares.throttling import ThrottlingMiddleware

pytestmark = pytest.mark.unit


class TestGameConfig:
    """GameConfig must support empty/partial TOML and expose all attributes used at startup."""

    def test_validate_empty_dict_uses_defaults(self) -> None:
        """Empty [game_config] section yields all defaults (robust startup)."""
        cfg = GameConfig.model_validate({})
        assert cfg.starting_points == 50
        assert cfg.send_gameover_sticker is True
        assert cfg.throttle_time_spin == 2
        assert cfg.throttle_time_other == 1
        assert cfg.throttle_time_top == 5

    def test_validate_partial_dict_merges_with_defaults(self) -> None:
        """Partial section fills only given keys."""
        cfg = GameConfig.model_validate({"throttle_time_spin": 3})
        assert cfg.throttle_time_spin == 3
        assert cfg.throttle_time_other == 1
        assert cfg.throttle_time_top == 5
        assert cfg.starting_points == 50

    def test_has_all_attributes_used_at_startup(self) -> None:
        """Every attribute read in __main__.py and middleware exists."""
        cfg = GameConfig.model_validate({})
        _ = cfg.starting_points
        _ = cfg.send_gameover_sticker
        _ = cfg.throttle_time_spin
        _ = cfg.throttle_time_other
        _ = cfg.throttle_time_top

    def test_throttling_middleware_accepts_game_config_attrs(self) -> None:
        """Exact call from __main__.py: ThrottlingMiddleware(spin, other, top) works."""
        cfg = GameConfig.model_validate({})
        mw = ThrottlingMiddleware(
            cfg.throttle_time_spin,
            cfg.throttle_time_other,
            cfg.throttle_time_top,
        )
        assert "spin" in mw.caches
        assert "default" in mw.caches
        assert "top" in mw.caches
        assert mw.caches["spin"].ttl == 2
        assert mw.caches["default"].ttl == 1
        assert mw.caches["top"].ttl == 5

    def test_throttling_middleware_optional_third_arg(self) -> None:
        """Middleware can be called with two args (throttle_time_top default 5)."""
        mw = ThrottlingMiddleware(1, 2)
        assert mw.caches["top"].ttl == 5


class TestGetConfigGameConfig:
    """get_config(model=GameConfig, ...) must return instance with all startup attributes."""

    def test_get_config_game_config_returns_all_attrs(self) -> None:
        """Loaded game_config has throttle_time_spin, throttle_time_other, throttle_time_top."""
        with patch("bot.config_reader.parse_config_file") as parse:
            parse.return_value = {
                "game_config": {
                    "starting_points": 100,
                    "send_gameover_sticker": False,
                    "throttle_time_spin": 3,
                    "throttle_time_other": 2,
                    "throttle_time_top": 10,
                },
            }
            get_config.cache_clear()
            try:
                cfg = get_config(model=GameConfig, root_key="game_config")
                assert cfg.throttle_time_spin == 3
                assert cfg.throttle_time_other == 2
                assert cfg.throttle_time_top == 10
                # Middleware construction must not raise
                ThrottlingMiddleware(
                    cfg.throttle_time_spin,
                    cfg.throttle_time_other,
                    cfg.throttle_time_top,
                )
            finally:
                get_config.cache_clear()


class TestBackupsConfig:
    """BackupsConfig must provide safe defaults for optional [backups] section."""

    def test_validate_empty_dict_uses_defaults(self) -> None:
        cfg = BackupsConfig.model_validate({})
        assert cfg.enabled is True
        assert cfg.retention_days == 7
        assert cfg.backup_dir == "/tmp/casino_backups"

    def test_validate_partial_dict_merges_with_defaults(self) -> None:
        cfg = BackupsConfig.model_validate({"enabled": False})
        assert cfg.enabled is False
        assert cfg.retention_days == 7
        assert cfg.backup_dir == "/tmp/casino_backups"

    def test_get_config_backups_returns_defaults_when_section_missing(self) -> None:
        with patch("bot.config_reader.parse_config_file") as parse:
            parse.return_value = {}
            get_config.cache_clear()
            try:
                cfg = get_config(model=BackupsConfig, root_key="backups", required=False)
                assert cfg.enabled is True
                assert cfg.retention_days == 7
                assert cfg.backup_dir == "/tmp/casino_backups"
            finally:
                get_config.cache_clear()


class TestCodeQualityReportConfig:
    """Daily code quality report config must be safe by default."""

    def test_validate_empty_dict_uses_safe_defaults(self) -> None:
        cfg = CodeQualityReportConfig.model_validate({})
        assert cfg.enabled is False
        assert cfg.hour == 0
        assert cfg.minute == 30
        assert cfg.log_since == "24h"
        assert cfg.log_until == "now"
        assert cfg.grep_pattern == "(warning|error|Error|Exception)"
        assert cfg.container_name == "python-runner"
        assert cfg.output_dir == "/tmp/casino_code_quality"
        assert cfg.opencode_timeout_seconds == 120
        assert cfg.max_extra_log_requests == 3
        assert cfg.max_extra_log_bytes == 102400

    def test_container_name_validation_rejects_shell_metacharacters(self) -> None:
        with pytest.raises(ValueError):
            CodeQualityReportConfig.model_validate({"container_name": "python-runner; rm -rf /"})

    def test_grep_pattern_validation_rejects_invalid_regex(self) -> None:
        with pytest.raises(ValueError):
            CodeQualityReportConfig.model_validate({"grep_pattern": "("})

    def test_get_config_returns_defaults_when_section_missing(self) -> None:
        with patch("bot.config_reader.parse_config_file") as parse:
            parse.return_value = {}
            get_config.cache_clear()
            try:
                cfg = get_config(
                    model=CodeQualityReportConfig,
                    root_key="code_quality_report",
                    required=False,
                )
                assert cfg.enabled is False
                assert cfg.output_dir == "/tmp/casino_code_quality"
            finally:
                get_config.cache_clear()
