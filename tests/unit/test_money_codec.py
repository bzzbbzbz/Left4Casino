"""Tests for TASK-016 money codec."""

import pytest

from bot.money import decode_money, encode_money


def test_money_codec_preserves_small_and_huge_signed_values() -> None:
    values = [1, 50, -50, 10**24, -(10**24)]
    for value in values:
        encoded = encode_money(value)
        assert isinstance(encoded, str)
        assert encoded == str(value)
        assert decode_money(encoded) == value


def test_money_codec_rejects_bool() -> None:
    with pytest.raises(TypeError):
        encode_money(True)
