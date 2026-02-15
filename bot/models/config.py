# [START SPEC:TASK-005:config-models]
"""Pydantic models for bot configuration."""

from pydantic import BaseModel, Field, field_validator


class BotConfig(BaseModel):
    """Bot configuration from settings.toml [bot] section."""

    token: str = Field(..., description="Telegram bot token")
    fsm_mode: str = Field(default="redis", description="FSM storage mode")

    @field_validator("fsm_mode")
    @classmethod
    def validate_fsm_mode(cls, v: str) -> str:
        if v not in ("redis", "memory"):
            raise ValueError("fsm_mode must be 'redis' or 'memory'")
        return v


class GameConfig(BaseModel):
    """Game configuration from settings.toml [game_config]."""

    starting_points: int = Field(default=50, ge=0)
    throttle_time_spin: int = Field(default=2, ge=0, le=10)
    throttle_time_other: int = Field(default=1, ge=0, le=10)
    throttle_time_top: int = Field(default=5, ge=0, le=30)

    @field_validator("starting_points")
    @classmethod
    def validate_starting_points(cls, v: int) -> int:
        if v < 0:
            raise ValueError("starting_points must be non-negative")
        return v


class HeistConfig(BaseModel):
    """Heist configuration from settings.toml [heist]."""

    enabled: bool = Field(default=True)
    pot_cap_multiplier: float = Field(default=0.05, gt=0, le=1.0)
    min_pot_multiplier: float = Field(default=0.01, gt=0, le=1.0)
    commission_pct: int = Field(default=10, ge=0, le=50)
    phase1_min_duration: int = Field(default=10, ge=5)
    phase1_max_duration: int = Field(default=25, le=30)
    phase2_min_duration: int = Field(default=2, ge=1)
    phase2_max_duration: int = Field(default=5, le=10)

    @field_validator("commission_pct")
    @classmethod
    def validate_commission(cls, v: int) -> int:
        """Комиссия не должна быть больше 50%."""
        if v > 50:
            raise ValueError("commission_pct cannot exceed 50%")
        return v


# [END SPEC:TASK-005:config-models]
