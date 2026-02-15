from enum import StrEnum, auto
from functools import lru_cache
from os import getenv
from tomllib import load
from typing import TypeVar

from pydantic import BaseModel, RedisDsn, SecretStr, field_validator

ConfigType = TypeVar("ConfigType", bound=BaseModel)


class LogRenderer(StrEnum):
    JSON = auto()
    CONSOLE = auto()


class FSMMode(StrEnum):
    MEMORY = auto()
    REDIS = auto()


class BotConfig(BaseModel):
    token: SecretStr
    fsm_mode: FSMMode

    @field_validator("fsm_mode", mode="before")
    @classmethod
    def fsm_mode_to_lower(cls, v: str):
        return v.lower()


class LogConfig(BaseModel):
    project_name: str = "my project"
    show_datetime: bool
    datetime_format: str
    show_debug_logs: bool
    time_in_utc: bool
    use_colors_in_console: bool
    renderer: LogRenderer
    allow_third_party_logs: bool

    @field_validator("renderer", mode="before")
    @classmethod
    def log_renderer_to_lower(cls, v: str):
        return v.lower()


class RedisConfig(BaseModel):
    dsn: RedisDsn


class GameConfig(BaseModel):
    starting_points: int
    send_gameover_sticker: bool
    throttle_time_spin: int
    throttle_time_other: int


class ChatRestrictionsConfig(BaseModel):
    block_private_chats: bool
    allowed_chat_ids: list[int]


class ReportsConfig(BaseModel):
    timezone: str = "UTC"
    admin_id: int = 0


class AIConfig(BaseModel):
    provider: str = "mock"
    api_key: str = "dummy"
    model: str = "gpt-4o-mini"
    credit_cooldown_minutes: int = 60


@lru_cache
def parse_config_file() -> dict:
    # Проверяем наличие переменной окружения, которая переопределяет путь к конфигу
    file_path = getenv("CONFIG_FILE_PATH")
    if file_path is None:
        error = "Could not find settings file"
        raise ValueError(error)
    # Читаем сам файл, пытаемся его распарсить как TOML
    with open(file_path, "rb") as file:
        config_data = load(file)
    return config_data


@lru_cache
def get_config(model: type[ConfigType], root_key: str) -> ConfigType:
    config_dict = parse_config_file()
    if root_key not in config_dict:
        error = f"Key {root_key} not found"
        raise ValueError(error)
    return model.model_validate(config_dict[root_key])
