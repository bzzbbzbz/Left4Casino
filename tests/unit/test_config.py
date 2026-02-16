"""Unit tests for config loading and startup-critical GameConfig usage."""

from unittest.mock import patch

import pytest
from bot.config_reader import GameConfig, get_config
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
