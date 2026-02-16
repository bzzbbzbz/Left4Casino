"""Unit tests for logging config: DropAiogramUpdateEvents and get_processors flag."""

from unittest.mock import MagicMock, patch

import pytest
import structlog
from structlog.stdlib import ProcessorFormatter

from bot.config_reader import LogConfig, LogRenderer
from bot.logs import DropAiogramUpdateEvents, get_processors, get_structlog_config

pytestmark = pytest.mark.unit


def _log_config(
    allow_third_party_logs: bool = False,
    show_datetime: bool = False,
    renderer: LogRenderer = LogRenderer.JSON,
) -> LogConfig:
    return LogConfig(
        project_name="test_project",
        show_datetime=show_datetime,
        datetime_format="%Y-%m-%d",
        show_debug_logs=False,
        time_in_utc=True,
        use_colors_in_console=False,
        renderer=renderer,
        allow_third_party_logs=allow_third_party_logs,
    )


class TestDropAiogramUpdateEvents:
    """DropAiogramUpdateEvents must raise DropEvent only for aiogram's 'Update id=... is handled'."""

    def test_raises_drop_event_for_aiogram_handled_message(self) -> None:
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {
            "event": "Update id=683547702 is handled. Duration 26 ms by bot id=8303683364"
        }
        with pytest.raises(structlog.DropEvent):
            processor(mock_logger, "info", event_dict.copy())

    def test_raises_drop_event_when_event_contains_both_substrings(self) -> None:
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {"event": "Update id=123 is handled. Duration 5 ms"}
        with pytest.raises(structlog.DropEvent):
            processor(mock_logger, "info", event_dict.copy())

    def test_does_not_raise_for_our_update_handled_message(self) -> None:
        """Our middleware logs 'Update handled' (no 'Update id=') — must not drop."""
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {"event": "Update handled", "user_id": 123}
        result = processor(mock_logger, "info", event_dict.copy())
        assert result["event"] == "Update handled"

    def test_does_not_raise_for_generic_message(self) -> None:
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {"event": "Something else"}
        result = processor(mock_logger, "info", event_dict.copy())
        assert result["event"] == "Something else"

    def test_does_not_raise_when_event_missing(self) -> None:
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {"level": "info"}
        result = processor(mock_logger, "info", event_dict.copy())
        assert result == {"level": "info"}

    def test_does_not_raise_when_event_not_string(self) -> None:
        processor = DropAiogramUpdateEvents()
        mock_logger = MagicMock()
        event_dict = {"event": 12345}
        result = processor(mock_logger, "info", event_dict.copy())
        assert result["event"] == 12345


class TestGetProcessorsIncludeDropAiogram:
    """get_processors(include_drop_aiogram=...) must control presence of DropAiogramUpdateEvents."""

    def test_include_drop_aiogram_true_adds_dropper(self) -> None:
        config = _log_config()
        processors = get_processors(config, include_drop_aiogram=True)
        assert any(isinstance(p, DropAiogramUpdateEvents) for p in processors)

    def test_include_drop_aiogram_false_omits_dropper(self) -> None:
        config = _log_config()
        processors = get_processors(config, include_drop_aiogram=False)
        assert not any(isinstance(p, DropAiogramUpdateEvents) for p in processors)

    def test_default_include_drop_aiogram_is_true(self) -> None:
        config = _log_config()
        processors_default = get_processors(config)
        processors_explicit = get_processors(config, include_drop_aiogram=True)
        assert any(isinstance(p, DropAiogramUpdateEvents) for p in processors_default)
        assert any(isinstance(p, DropAiogramUpdateEvents) for p in processors_explicit)


class TestGetStructlogConfigThirdPartyHandler:
    """When allow_third_party_logs=True, stdlib handler must use processors WITHOUT DropAiogramUpdateEvents."""

    def test_third_party_handler_formatter_has_no_drop_processor(self) -> None:
        config = _log_config(allow_third_party_logs=True)
        mock_root = MagicMock()
        with patch("bot.logs.logging.getLogger", return_value=mock_root):
            get_structlog_config(config)
        mock_root.addHandler.assert_called_once()
        handler = mock_root.addHandler.call_args[0][0]
        formatter = handler.formatter
        assert isinstance(formatter, ProcessorFormatter)
        processors = formatter.processors
        if callable(processors):
            processors = processors()
        assert not any(isinstance(p, DropAiogramUpdateEvents) for p in processors), (
            "Stdlib ProcessorFormatter must not use DropAiogramUpdateEvents to avoid crashing aiogram tasks"
        )

    def test_structlog_own_config_includes_dropper(self) -> None:
        config = _log_config(allow_third_party_logs=False)
        result = get_structlog_config(config)
        processors = result["processors"]
        assert any(isinstance(p, DropAiogramUpdateEvents) for p in processors)
