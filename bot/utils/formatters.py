"""
Утилиты для форматирования данных в читаемый вид.
"""


def format_number(num: int | float) -> str:
    """
    Форматирует число с разделителями разрядов (пробелы) для чисел >= 1000.

    Args:
        num: Число для форматирования

    Returns:
        Отформатированная строка с разделителями разрядов (пробелами)

    Examples:
        >>> format_number(50)
        '50'
        >>> format_number(999)
        '999'
        >>> format_number(1000)
        '1 000'
        >>> format_number(1234567)
        '1 234 567'
        >>> format_number(-500000)
        '-500 000'
    """
    if abs(num) >= 1_000:
        # Используем встроенное форматирование с запятыми, затем заменяем на пробелы
        return f"{int(num):,}".replace(",", " ")
    if isinstance(num, float) and not num.is_integer():
        return str(num)
    return str(int(num))
