"""Unit tests for slot dice logic (bot/dice_check.py)."""

import pytest

from bot.dice_check import get_combo_parts, get_score_change

pytestmark = pytest.mark.unit

# Winning combinations from implementation:
# three-of-a-kind (except 777): dice 1, 22, 43 → +7
# two 7's (BAR style): dice 16, 32, 48 → +5
# jackpot 777: dice 64 → +10
# all other: -1

VALID_SYMBOLS = ["bar", "grapes", "lemon", "seven"]


class TestGetScoreChange:
    """Tests for get_score_change(dice_value) mapping."""

    @pytest.mark.parametrize(
        "dice_value,expected_score",
        [
            (1, 7),
            (22, 7),
            (43, 7),
        ],
    )
    def test_three_of_a_kind_returns_7(self, dice_value: int, expected_score: int) -> None:
        """Three-of-a-kind (except 777) gives +7."""
        assert get_score_change(dice_value) == expected_score

    @pytest.mark.parametrize(
        "dice_value,expected_score",
        [
            (16, 5),
            (32, 5),
            (48, 5),
        ],
    )
    def test_two_sevens_returns_5(self, dice_value: int, expected_score: int) -> None:
        """Two 7's (BAR-BAR-BAR style) gives +5."""
        assert get_score_change(dice_value) == expected_score

    def test_jackpot_777_returns_10(self) -> None:
        """Jackpot (777) gives +10."""
        assert get_score_change(64) == 10

    @pytest.mark.parametrize(
        "dice_value",
        [
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            17,
            18,
            19,
            20,
            21,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            44,
            45,
            46,
            47,
            49,
            50,
            51,
            52,
            53,
            54,
            55,
            56,
            57,
            58,
            59,
            60,
            61,
            62,
            63,
        ],
    )
    def test_losing_combination_returns_minus_one(self, dice_value: int) -> None:
        """Non-winning combinations give -1."""
        assert get_score_change(dice_value) == -1

    def test_all_dice_values_return_valid_score(self) -> None:
        """Every dice value 1-64 returns one of -1, 5, 7, 10."""
        valid_scores = {-1, 5, 7, 10}
        for dice_value in range(1, 65):
            score = get_score_change(dice_value)
            assert score in valid_scores, f"dice_value={dice_value} returned {score}"

    def test_win_rate_in_reasonable_range(self) -> None:
        """Win probability is in a reasonable range (7/64 ≈ 10.9% in current mapping)."""
        wins = sum(1 for dice in range(1, 65) if get_score_change(dice) > 0)
        win_rate = wins / 64
        assert 0.05 <= win_rate <= 0.35, f"win_rate={win_rate:.2%} outside 5-35%"


class TestGetComboParts:
    """Tests for get_combo_parts(dice_value) mapping."""

    def test_returns_three_elements(self) -> None:
        """Combo parts always has exactly 3 symbols."""
        for dice_value in range(1, 65):
            parts = get_combo_parts(dice_value)
            assert len(parts) == 3, f"dice_value={dice_value} gave {len(parts)} parts"

    def test_all_parts_are_valid_symbols(self) -> None:
        """Each part is one of bar, grapes, lemon, seven."""
        for dice_value in range(1, 65):
            parts = get_combo_parts(dice_value)
            for part in parts:
                assert part in VALID_SYMBOLS, f"dice_value={dice_value} part {part!r} invalid"

    def test_dice_64_is_seven_seven_seven(self) -> None:
        """Dice 64 (jackpot) is seven, seven, seven."""
        assert get_combo_parts(64) == ["seven", "seven", "seven"]
