from enum import StrEnum, auto
from functools import lru_cache
from os import getenv
from tomllib import load
from typing import TypeVar

from pydantic import BaseModel, Field, RedisDsn, SecretStr, field_validator

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
    """Game configuration from [game_config]. All fields have defaults for robust startup."""

    starting_points: int = Field(default=50, ge=0)
    send_gameover_sticker: bool = True
    throttle_time_spin: int = Field(default=2, ge=0, le=60)
    throttle_time_other: int = Field(default=1, ge=0, le=60)
    throttle_time_top: int = Field(default=5, ge=0, le=60)


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


class DiceFightsConfig(BaseModel):
    challenge_timeout_minutes: int = 5
    roll_timeout_minutes: int = 5
    max_debt: int = 100
    min_bet: int = 1


class HappyMomentTierConfig(BaseModel):
    duration_minutes: int
    multiplier: float


class HappyMomentConfig(BaseModel):
    enabled: bool = True
    events_per_day: int = 2
    active_hours_weight: int = 90
    active_hours_start: str = "08:00"
    active_hours_end: str = "02:00"
    tiers: list[HappyMomentTierConfig] = []


class HeistConfig(BaseModel):
    enabled: bool = True
    events_per_day: int = 1
    active_hours_start: str = "08:00"
    active_hours_end: str = "02:00"
    pot_cap_pct: float = 7.0
    min_pot_pct: float = 1.5
    seed_min_pct: float = 0.5
    seed_max_pct: float = 2.0
    commission_pct: int = 15
    base_value_noise_pct: float = 15.0
    base_value_fallback: int = 1000
    warning_before_minutes: int = 10
    phase1_min_minutes: int = 10
    phase1_max_minutes: int = 25
    phase2_min_minutes: int = 2
    phase2_max_minutes: int = 5
    seed_delay_minutes: float = 0.1
    max_duration_minutes: int = 30
    croupier_message_interval_seconds: int = 120


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
def get_config(model: type[ConfigType], root_key: str, required: bool = True) -> ConfigType:
    config_dict = parse_config_file()
    if root_key not in config_dict:
        if required:
            error = f"Key {root_key} not found"
            raise ValueError(error)
        return model.model_validate({})
    return model.model_validate(config_dict[root_key])
