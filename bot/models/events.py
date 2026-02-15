# [START SPEC:TASK-005:events-models]
"""Pydantic models for game events."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GameEvent(BaseModel):
    """Base model for all game events."""

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    event_id: str = Field(..., description="Unique event ID (UUID)")
    user_id: int = Field(..., gt=0, description="Telegram user ID")
    event_type: str = Field(..., description="Type of event")
    amount: int = Field(..., description="Amount of points (can be negative)")
    created_at: datetime = Field(default_factory=datetime.now)
    chat_id: int | None = Field(None, description="Chat ID where event occurred")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional event data")


class WinEvent(GameEvent):
    """Player won in slots."""

    event_type: Literal["win"] = "win"
    amount: int = Field(..., gt=0, description="Win amount (positive)")

    @field_validator("metadata")
    @classmethod
    def validate_win_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure win events have required metadata (bid and score/jackpot info)."""
        if "bid" not in v:
            raise ValueError("Win event must have 'bid' in metadata")
        if not any(k in v for k in ("base_score", "base_score_change")):
            raise ValueError("Win event must have 'base_score' or 'base_score_change' in metadata")
        if not any(k in v for k in ("jackpot_multiplier", "super_jackpot_multiplier")):
            raise ValueError(
                "Win event must have 'jackpot_multiplier' or 'super_jackpot_multiplier' in metadata"
            )
        return v


class LossEvent(GameEvent):
    """Player lost in slots."""

    event_type: Literal["loss"] = "loss"
    amount: int = Field(..., lt=0, description="Loss amount (negative)")


class TransferEvent(GameEvent):
    """Player transferred points to another player."""

    event_type: Literal["transfer"] = "transfer"
    amount: int = Field(..., gt=0, description="Transfer amount")

    @field_validator("metadata")
    @classmethod
    def validate_transfer_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure transfer has recipient."""
        if "to_user_id" not in v:
            raise ValueError("Transfer event must have 'to_user_id' in metadata")
        return v


class HeistContributionEvent(GameEvent):
    """Player contributed to heist pot (amount stored as negative = bid to pot)."""

    event_type: Literal["heist_contribution"] = "heist_contribution"

    @field_validator("metadata")
    @classmethod
    def validate_heist_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure heist events have pot info."""
        if "pot_after" not in v:
            raise ValueError("Heist event must have 'pot_after'")
        return v


class HappyMomentWinEvent(GameEvent):
    """Player won during happy moment."""

    event_type: Literal["happy_moment_win"] = "happy_moment_win"
    amount: int = Field(..., gt=0)

    @field_validator("metadata")
    @classmethod
    def validate_happy_moment_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Ensure happy moment wins have multiplier."""
        if "happy_moment_multiplier" not in v:
            raise ValueError("Happy moment event must have multiplier")
        return v


def create_event(event_type: str, **kwargs: Any) -> GameEvent:
    """Create appropriate event model based on type."""
    event_map: dict[str, type[GameEvent]] = {
        "win": WinEvent,
        "loss": LossEvent,
        "transfer": TransferEvent,
        "heist_contribution": HeistContributionEvent,
        "happy_moment_win": HappyMomentWinEvent,
    }
    model_class = event_map.get(event_type, GameEvent)
    return model_class(event_type=event_type, **kwargs)


# [END SPEC:TASK-005:events-models]
