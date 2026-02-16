# Semantic Regions Guide

Единый формат семантических регионов для критичного кода проекта Left4Casino. Регионы помогают AI и разработчикам видеть границы логических блоков, связь с требованиями и не изменять game balance без явного запроса.

---

## Формат маркеров

### Базовый формат

```python
# [START SPEC:{SPEC_ID}:{REGION_NAME}]
# REQ: {Краткое описание требования}
# Source: {SPEC_FILE.md, секция}
# CRITICAL: {Опционально: что нельзя менять без ревью}

def critical_function():
    """Docstring как обычно."""
    # implementation
    pass

# [END SPEC:{SPEC_ID}]
```

- **SPEC_ID** — идентификатор фичи или аспекта (например `HEIST-ECONOMY`, `DICE-BALANCE`).
- **REGION_NAME** — короткое имя региона (функция, метод, блок).
- **REQ** — формула или описание требования из спецификации.
- **Source** — файл спеки и секция для прослеживаемости.
- **CRITICAL** — предупреждение для AI/ревьюера.

---

## Соглашения по SPEC_ID

| Формат | Пример | Назначение |
|--------|--------|------------|
| `{FEATURE}-{ASPECT}` | `HEIST-ECONOMY` | Экономика ограбления |
| | `HEIST-PHASES` | Переходы фаз ограбления |
| | `DICE-BALANCE` | Баланс слотов (очки за комбинации) |
| | `SAFE-ATOMIC` | Атомарные операции сейфа |
| | `AI-CREDIT-EVAL` | Оценка ответа в AI-кредите |
| | `DEBT-SETTLEMENT` | Взаимозачёт долгов PvP |
| `TASK-XXX` | `TASK-011` | Код из задачи по спецификации |

---

## Типы регионов

### 1. Функция / метод

```python
# [START SPEC:HEIST-ECONOMY:calculate_pot_cap]
# REQ: pot_cap = base_winnings * 5% (с fallback к 1000)
# Source: HEIST_SPEC.md, секция "Экономика"
# CRITICAL: Множитель влияет на длительность ивента и game balance
def calculate_pot_cap(self, base_winnings: int) -> int:
    """Рассчитать максимальный размер банка."""
    if base_winnings < 1000:
        base_winnings = 1000
    return int(base_winnings * self.pot_cap_multiplier)
# [END SPEC:HEIST-ECONOMY]
```

### 2. Класс (несколько методов)

```python
# [START SPEC:DICE-BALANCE:SlotCombinations]
# REQ: Маппинг dice 1-64 на комбинации слотов и очки
# Source: dice_check.py, оригинальная реализация
# CRITICAL: Изменение очков влияет на game balance
def get_score_change(dice_value: int) -> int:
    ...
def get_combo_parts(dice_value: int) -> list[str]:
    ...
# [END SPEC:DICE-BALANCE]
```

### 3. Блок кода внутри функции

```python
def create_or_update_debt(self, ...):
    # [START SPEC:DEBT-SETTLEMENT:MutualOffset]
    # REQ: Если A должен B и B должен A — долги взаимно сокращаются
    # Source: DICE_FIGHT_SPEC.md, "Взаимозачёт долгов"
    if reverse:
        # net reverse debt with new debt
        ...
    # [END SPEC:DEBT-SETTLEMENT]
```

---

## Когда добавлять регионы

**Всегда:**
- Расчёты game balance (выигрыши, множители, pot_cap).
- Атомарные транзакции (переводы, сейф).
- Сложная логика с граничными случаями (взаимозачёт долгов).
- Новый код по спецификациям TASK-001+.

**По возможности:**
- Часто меняемая бизнес-логика.
- Код с неочевидными требованиями.

**Не нужно:**
- Простой CRUD, утилиты, форматтеры.
- Middleware, декораторы.
- Однострочники и константы без влияния на баланс.

---

## Проверка

Запуск скрипта верификации:

```bash
python scripts/verify_regions.py
```

Скрипт находит все маркеры `[START SPEC:...]`, проверяет наличие SPEC_ID в `docs/specs/` и выводит отчёт.

---

## Ссылки

- `AGENTS.md` — секция "Semantic Regions", skill:code.
- `.cursorrules` — инструкции для AI по маркерам.
- `docs/specs/` — спецификации для Source.
