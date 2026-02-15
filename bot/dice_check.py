# Source: https://gist.github.com/MasterGroosha/963c0a82df348419788065ab229094ac

import random
from functools import lru_cache

from fluent.runtime import FluentLocalization


# [START SPEC:DICE-BALANCE:get_score_change]
# REQ: Map dice 1-64 to slot win/loss: three-of-a-kind +7, BAR BAR BAR +5, 777 +10, else -1
# Source: dice_check.py, original implementation
# CRITICAL: Changing these values affects game balance
@lru_cache(maxsize=64)
def get_score_change(dice_value: int) -> int:
    """
    Checks for the winning combination

    :param dice_value: dice value (1-64)
    :return: user score change (integer)
    """

    # three-of-a-kind (except 777)
    if dice_value in (1, 22, 43):
        return 7
    # starting with two 7's (again, except 777)
    elif dice_value in (16, 32, 48):
        return 5
    # jackpot (777)
    elif dice_value == 64:
        return 10
    else:
        return -1


# [END SPEC:DICE-BALANCE]


# [START SPEC:DICE-BALANCE:get_combo_parts]
# REQ: Map dice value 1-64 to three slot symbols (bar, grapes, lemon, seven)
# Source: dice_check.py, original implementation
# CRITICAL: Values are translation keys; mapping must stay consistent with get_score_change
def get_combo_parts(dice_value: int) -> list[str]:
    """
    Returns exact icons from dice (bar, grapes, lemon, seven).
    Do not edit these values, since they are subject to be translated
    by outer code.
    :param dice_value: dice value (1-64)
    :return: list of icons' texts
    """

    # Alternative way (credits to t.me/svinerus):
    #   return [casino[(dice_value - 1) // i % 4]for i in (1, 4, 16)]

    # Do not edit these values; they are actually translation keys
    #           0       1         2        3
    values = ["bar", "grapes", "lemon", "seven"]

    dice_value -= 1
    result = []
    for _ in range(3):
        result.append(values[dice_value % 4])
        dice_value //= 4
    return result


# [END SPEC:DICE-BALANCE]


@lru_cache(maxsize=64)
def get_combo_text(dice_value: int, l10n: FluentLocalization) -> str:
    """
    Returns localized string with dice result
    :param dice_value: dice value (1-64)
    :param l10n: Fluent localization object
    :return: string with localized result
    """
    parts: list[str] = get_combo_parts(dice_value)
    for i in range(len(parts)):
        parts[i] = l10n.format_value(parts[i])
    return ", ".join(parts)


# [START SPEC:DICE-BALANCE:get_super_jackpot]
# REQ: 15% chance Super Jackpot; weights x2 65%, x3 25%, x5 9%, x10 1%
# Source: AGENTS.md "Slots (🎰)" / game balance
# CRITICAL: Weights and trigger chance affect economy
def get_super_jackpot() -> tuple[int, str | None]:
    """
    Calculates Super Jackpot multiplier.
    Returns (multiplier, jackpot_name).
    Multiplier is 1 if no jackpot.
    """
    # 15% chance to trigger Super Jackpot
    if random.random() > 0.15:
        return 1, None

    # Weighted choice for multiplier
    # x2 (Mini): 65%, x3 (Major): 25%, x5 (Mega): 9%, x10 (Grand): 1%
    multipliers = [2, 3, 5, 10]
    weights = [65, 25, 9, 1]
    names = {2: "Mini", 3: "Major", 5: "Mega", 10: "Grand"}

    multiplier = random.choices(multipliers, weights=weights, k=1)[0]
    return multiplier, names[multiplier]


# [END SPEC:DICE-BALANCE]
