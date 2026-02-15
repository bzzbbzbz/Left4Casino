# [START SPEC:TASK-005:entity-models]
"""Pydantic models for database entities."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class User(BaseModel):
    """User entity from database (users table)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int = Field(..., gt=0)
    balance: int = Field(default=50)
    safe_balance: int = Field(default=0, ge=0)
    bid: int = Field(default=1, ge=1)
    state: Literal["IDLE", "IN_DIALOGUE"] = Field(default="IDLE")
    nickname: str | None = None
    games_played: int = Field(default=0, ge=0)
    total_won: int = Field(default=0, ge=0)
    total_lost: int = Field(default=0, ge=0)
    bankruptcy_count: int = Field(default=0, ge=0)
    created_at: datetime | None = Field(default=None)

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v: object) -> str:
        if v is None or v == "":
            return "IDLE"
        s = str(v).upper()
        return s if s in ("IDLE", "IN_DIALOGUE") else "IDLE"


class DiceChallenge(BaseModel):
    """Dice challenge entity (dice_challenges table)."""

    model_config = ConfigDict(from_attributes=True)

    challenge_id: str = Field(...)
    chat_id: int = Field(...)
    initiator_id: int = Field(..., gt=0)
    opponent_id: int | None = None
    bet_amount: int = Field(..., gt=0)
    status: Literal["pending", "accepted", "rolling", "completed", "cancelled", "expired"] = Field(
        default="pending"
    )
    challenger_roll: int | None = Field(None, ge=1, le=6)
    opponent_roll: int | None = Field(None, ge=1, le=6)
    created_at: datetime | None = None
    expires_at: datetime | None = None


# [END SPEC:TASK-005:entity-models]
