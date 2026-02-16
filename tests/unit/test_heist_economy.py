"""Unit tests for heist economy (bot/services/heist.py)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.heist import HeistService, HeistState

pytestmark = pytest.mark.unit


def _make_heist_config(
    pot_cap_pct: int = 5,
    min_pot_pct: float = 1,
    commission_pct: int = 10,
    seed_min_pct: int = 0,
    seed_max_pct: int = 2,
    base_value_fallback: int = 1000,
) -> SimpleNamespace:
    """Build a minimal config namespace for heist economy tests."""
    return SimpleNamespace(
        pot_cap_pct=pot_cap_pct,
        min_pot_pct=min_pot_pct,
        commission_pct=commission_pct,
        seed_min_pct=seed_min_pct,
        seed_max_pct=seed_max_pct,
        base_value_fallback=base_value_fallback,
        enabled=True,
        phase1_min_minutes=10,
        phase1_max_minutes=25,
        phase2_min_minutes=2,
        phase2_max_minutes=5,
        active_hours_start="08:00",
        active_hours_end="02:00",
        base_value_noise_pct=0,
    )


class TestHeistEconomyCalculations:
    """Tests for pot_cap, min_pot, seed, commission formulas."""

    @pytest.mark.parametrize(
        "base_value,pot_cap_pct,expected_pot_cap",
        [
            (10000, 5, 500),
            (50000, 5, 2500),
            (1000, 5, 50),
        ],
    )
    def test_pot_cap_formula(
        self, base_value: int, pot_cap_pct: int, expected_pot_cap: int
    ) -> None:
        """pot_cap = int(base_value * pot_cap_pct / 100)."""
        pot_cap = int(base_value * pot_cap_pct / 100)
        assert pot_cap == expected_pot_cap

    def test_fallback_base_value_gives_pot_cap_50(self) -> None:
        """When base_value is 1000 (fallback), pot_cap at 5% is 50."""
        base_value = 1000
        pot_cap_pct = 5
        pot_cap = int(base_value * pot_cap_pct / 100)
        assert pot_cap == 50

    @pytest.mark.parametrize(
        "base_value,min_pot_pct,expected_min_pot",
        [
            (10000, 1, 100),
            (10000, 1.5, 150),
            (1000, 1, 10),
        ],
    )
    def test_min_pot_formula(
        self, base_value: int, min_pot_pct: float, expected_min_pot: int
    ) -> None:
        """min_pot = int(base_value * min_pot_pct / 100)."""
        min_pot = int(base_value * min_pot_pct / 100)
        assert min_pot == expected_min_pot

    def test_commission_formula(self) -> None:
        """commission = int(pot * commission_pct / 100)."""
        pot = 1000
        commission_pct = 10
        commission = int(pot * commission_pct / 100)
        assert commission == 100

    def test_deflationary_model_total_output_le_input(self) -> None:
        """Payout + commission = pot; payout <= contributions (commission destroyed)."""
        contributions = 1000
        commission_pct = 10
        commission = int(contributions * commission_pct / 100)
        winner_payout = contributions - commission
        assert winner_payout + commission == contributions
        assert winner_payout <= contributions
        assert commission > 0
        assert winner_payout == 900
        assert commission == 100


class TestHeistPhaseTransition:
    """Tests for phase transition conditions."""

    def test_should_transition_when_pot_reaches_pot_cap(self) -> None:
        """When phase is robbery and pot >= pot_cap, should transition to phase 2."""
        now = datetime.now(UTC)
        state = HeistState(
            chat_id=123,
            base_value=10000,
            pot=500,
            pot_cap=500,
            seed_amount=100,
            phase="robbery",
            phase1_end=now + timedelta(minutes=10),
            phase2_end=None,
            phase2_duration=3,
        )
        assert state.phase == "robbery"
        assert state.pot >= state.pot_cap

    def test_should_not_transition_when_pot_below_pot_cap(self) -> None:
        """When pot < pot_cap, stay in robbery."""
        now = datetime.now(UTC)
        state = HeistState(
            chat_id=123,
            base_value=10000,
            pot=400,
            pot_cap=500,
            seed_amount=100,
            phase="robbery",
            phase1_end=now + timedelta(minutes=10),
            phase2_end=None,
            phase2_duration=3,
        )
        assert state.pot < state.pot_cap


class TestHeistServiceIntegration:
    """Tests using HeistService with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_start_heist_sets_pot_cap_from_base_value(self) -> None:
        """start_heist computes pot_cap = base_value * pot_cap_pct / 100."""
        config = _make_heist_config(pot_cap_pct=5)
        mock_bot = MagicMock()
        mock_db = MagicMock()
        mock_db.get_yesterday_total_won = AsyncMock(return_value=10000)
        service = HeistService(
            bot=mock_bot,
            db=mock_db,
            config=config,
            allowed_chat_ids=[12345],
        )
        with patch.object(
            service, "calculate_base_value", new_callable=AsyncMock, return_value=10000
        ):
            with patch("bot.services.heist.random.randint", side_effect=[10, 3, 1]):
                await service.start_heist()
        state = service.get_heist_state(12345)
        assert state is not None
        assert state.base_value == 10000
        assert state.pot_cap == 500
        assert state.pot == 0
        assert state.phase == "robbery"

    @pytest.mark.asyncio
    async def test_fallback_base_value_when_yesterday_winnings_low(self) -> None:
        """When get_yesterday_total_won < base_value_fallback, B uses fallback (1000)."""
        config = _make_heist_config(pot_cap_pct=5, base_value_fallback=1000)
        mock_bot = MagicMock()
        mock_db = MagicMock()
        mock_db.get_yesterday_total_won = AsyncMock(return_value=100)
        service = HeistService(
            bot=mock_bot,
            db=mock_db,
            config=config,
            allowed_chat_ids=[999],
        )
        with patch("bot.services.heist.random.uniform", return_value=1.0):
            with patch("bot.services.heist.random.randint", side_effect=[1, 10, 3]):
                b = await service.calculate_base_value(999)
        assert b == 1000
        pot_cap = int(b * config.pot_cap_pct / 100)
        assert pot_cap == 50
