# TASK-004: Basic Unit Tests Implementation

**ID**: TASK-004  
**Title**: Написание базовых unit-тестов для критичной логики  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-004-1: Test structure setup
Создать структуру директорий для тестов.

**Acceptance Criteria:**
- Создана директория `tests/` в корне проекта
- Создана `tests/unit/` для unit-тестов
- Создан `tests/conftest.py` с общими фикстурами
- Создан `tests/__init__.py` (пустой)

### REQ-004-2: test_dice_check.py
Тесты для логики расчёта выигрышей в слотах.

**Acceptance Criteria:**
- Файл `tests/unit/test_dice_check.py` создан
- Тестируются все комбинации выигрышей (777, BAR-BAR-BAR, три одинаковых)
- Тестируются все случаи проигрышей
- Тестируется маппинг dice values (1-64) на комбинации барабанов
- Coverage: 100% для `bot/dice_check.py`

### REQ-004-3: test_heist_economy.py
Тесты для экономики ограбления банка.

**Acceptance Criteria:**
- Файл `tests/unit/test_heist_economy.py` создан
- Тестируется расчёт `pot_cap`, `min_pot`, `seed` от base_winnings
- Тестируется fallback при base_winnings < 1000
- Тестируется расчёт комиссии крупье
- Тестируется дефляционная модель (сумма выплат <= суммы вложений)
- Coverage: ключевые методы `HeistService` покрыты

### REQ-004-4: pytest configuration
Настроить pytest для асинхронных тестов.

**Acceptance Criteria:**
- `pytest-asyncio` установлен
- В `pyproject.toml` добавлена секция `[tool.pytest.ini_options]`
- Async тесты работают с декоратором `@pytest.mark.asyncio`
- Команда `pytest tests/` успешно запускается

---

## 🎯 Goals

**Primary Goal:**
Создать базовый набор тестов для защиты критичной игровой логики от регрессий при рефакторинге.

**Why This Matters:**
- **Game Balance**: Ошибка в dice_check может сломать экономику (например, все выигрывают вместо проигрыша)
- **Heist Economy**: Неправильный расчёт комиссии может привести к инфляции/дефляции
- **Confidence in Changes**: С тестами можно смело рефакторить код
- **Documentation**: Тесты показывают, как должна работать логика

---

## 📐 Design

### Directory Structure
```
tests/
├── __init__.py
├── conftest.py              # Общие фикстуры
└── unit/
    ├── __init__.py
    ├── test_dice_check.py   # Тесты логики слотов
    └── test_heist_economy.py # Тесты экономики heist
```

### Test Strategy

#### test_dice_check.py
```python
import pytest
from telegram-casino-bot.bot.dice_check import (
    get_slot_combination,
    calculate_base_score,
    is_winning_combination,
)

class TestSlotCombinations:
    """Тесты маппинга dice → slot combinations"""
    
    def test_dice_1_maps_to_correct_combination(self):
        """Проверяем, что dice=1 даёт ожидаемую комбинацию"""
        combination = get_slot_combination(1)
        assert combination in [(1,1,1), (2,2,2), ...]  # Зависит от реализации
    
    def test_all_dice_values_are_valid(self):
        """Проверяем, что все значения 1-64 дают валидные комбинации"""
        for dice_value in range(1, 65):
            combination = get_slot_combination(dice_value)
            assert len(combination) == 3
            assert all(1 <= x <= 7 for x in combination)  # Assuming 7 symbols

class TestWinCalculation:
    """Тесты расчёта выигрыша"""
    
    @pytest.mark.parametrize("combination,expected_score", [
        ((7, 7, 7), 10),  # 777 = +10
        ((3, 3, 3), 7),   # Три одинаковых = +7
        ((6, 6, 6), 5),   # BAR-BAR-BAR = +5 (assuming 6=BAR)
        ((1, 2, 3), -1),  # Проигрыш = -1
    ])
    def test_base_score_calculation(self, combination, expected_score):
        """Проверяем правильность базовых выигрышей"""
        score = calculate_base_score(combination)
        assert score == expected_score
    
    def test_win_probability_is_balanced(self):
        """Проверяем, что вероятность выигрыша ~20-30% (game balance)"""
        wins = sum(1 for dice in range(1, 65) 
                   if calculate_base_score(get_slot_combination(dice)) > 0)
        win_rate = wins / 64
        assert 0.15 <= win_rate <= 0.35  # Reasonable range
```

#### test_heist_economy.py
```python
import pytest
from telegram-casino-bot.bot.services.heist import HeistService

class TestHeistEconomyCalculations:
    """Тесты расчёта параметров экономики"""
    
    @pytest.mark.parametrize("base_winnings,expected_pot_cap", [
        (10000, 500),   # 10000 * 0.05 = 500
        (50000, 2500),  # 50000 * 0.05 = 2500
        (100, 50),      # Fallback: используется 1000 * 0.05 = 50
    ])
    def test_pot_cap_calculation(self, base_winnings, expected_pot_cap):
        """Проверяем расчёт максимального размера банка"""
        heist = HeistService(chat_id=123)
        pot_cap = heist.calculate_pot_cap(base_winnings)
        assert pot_cap == expected_pot_cap
    
    def test_fallback_when_base_winnings_too_low(self):
        """Проверяем fallback к 1000 при малых выигрышах"""
        heist = HeistService(chat_id=123)
        pot_cap = heist.calculate_pot_cap(base_winnings=100)
        # Should use 1000 as fallback
        assert pot_cap == 50  # 1000 * 0.05
    
    def test_commission_calculation(self):
        """Проверяем расчёт комиссии крупье"""
        heist = HeistService(chat_id=123)
        pot = 1000
        commission_pct = 10
        commission = heist.calculate_commission(pot, commission_pct)
        assert commission == 100  # 1000 * 0.10
    
    def test_deflationary_model_total_output_le_input(self):
        """Проверяем дефляционную модель: выплаты ≤ взносов"""
        # Simulate heist
        contributions = 1000  # Total player contributions
        commission_pct = 10
        
        winner_payout = contributions * (100 - commission_pct) / 100
        commission = contributions * commission_pct / 100
        
        total_output = winner_payout  # Commission destroyed
        assert total_output <= contributions
        assert commission + winner_payout == contributions

class TestHeistPhaseTransitions:
    """Тесты переходов между фазами"""
    
    @pytest.mark.asyncio
    async def test_transition_to_phase_2_when_pot_cap_reached(self):
        """Проверяем досрочный переход в фазу 2 при достижении pot_cap"""
        heist = HeistService(chat_id=123)
        heist.pot_cap = 500
        heist.pot = 500
        
        should_transition = heist.should_transition_to_phase_2()
        assert should_transition is True
```

### Fixtures (conftest.py)
```python
import pytest
import asyncio
from typing import AsyncGenerator

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_db():
    """Mock database for tests"""
    # TODO: Implement mock DB or use in-memory SQLite
    pass
```

---

## ✅ Implementation Checklist

### Phase 1: Setup
- [ ] Создать `tests/` структуру
- [ ] Установить `pytest`, `pytest-asyncio`
- [ ] Создать `conftest.py` с базовыми фикстурами
- [ ] Обновить `pyproject.toml` с `[tool.pytest.ini_options]`

### Phase 2: test_dice_check.py
- [ ] Прочитать `bot/dice_check.py` для понимания логики
- [ ] Написать тесты маппинга dice → combinations
- [ ] Написать параметризованные тесты для расчёта score
- [ ] Написать тест на game balance (win rate)
- [ ] Запустить: `pytest tests/unit/test_dice_check.py -v`

### Phase 3: test_heist_economy.py
- [ ] Прочитать `bot/services/heist.py` для понимания экономики
- [ ] Написать тесты расчёта pot_cap, min_pot, seed
- [ ] Написать тест fallback при низких выигрышах
- [ ] Написать тест дефляционной модели
- [ ] Написать тесты переходов фаз
- [ ] Запустить: `pytest tests/unit/test_heist_economy.py -v`

### Phase 4: Documentation
- [ ] Добавить секцию "Testing" в `AGENTS.md`
- [ ] Документировать команды: `pytest tests/`, `pytest -v`, `pytest --cov`
- [ ] Добавить badge в README (опционально)

---

## 🧪 Testing & Validation

### Run Tests
```bash
# Все тесты
pytest tests/

# С подробным выводом
pytest tests/ -v

# Только unit тесты
pytest tests/unit/

# С coverage (если установлен pytest-cov)
pytest tests/ --cov=telegram-casino-bot/bot --cov-report=html
```

### Success Metrics
- Все тесты проходят (зелёные)
- Coverage для `dice_check.py`: 100%
- Coverage для ключевых методов `HeistService`: > 80%
- Тесты запускаются за < 5 секунд (быстрые unit-тесты)

### Manual Validation
1. Изменить логику в `dice_check.py` (например, изменить выигрыш 777 с +10 на +5)
2. Запустить тесты — должен быть failed test
3. Откатить изменение — тесты снова зелёные

---

## 📦 Dependencies

**Before this task:**
- TASK-002 (pyproject.toml) — рекомендуется (но не обязательно)
- Код `bot/dice_check.py` и `bot/services/heist.py` существует

**After this task:**
- Используется в pre-commit (опционально)
- Используется в CI/CD (TASK-012)
- Служит документацией для разработчиков

---

## 📝 Notes

### Test Naming Convention
```python
# Pattern: test_<what>_<condition>_<expected_result>
def test_calculate_score_with_777_returns_10():
    pass

def test_pot_cap_when_base_winnings_too_low_uses_fallback():
    pass
```

### Parametrized Tests
Используйте `@pytest.mark.parametrize` для тестирования множества входных данных:
```python
@pytest.mark.parametrize("input,expected", [
    (1, 10),
    (2, 20),
    (3, 30),
])
def test_multiple_cases(input, expected):
    assert function(input) == expected
```

### Async Tests
Для асинхронных функций используйте:
```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected
```

### Mocking
Для изоляции unit-тестов можно использовать `unittest.mock` или `pytest-mock`:
```python
def test_with_mock(mocker):
    mock_db = mocker.patch('bot.db.Database')
    # Test logic
```

### Future Expansion
После этой задачи можно добавить:
- `test_ai_credit_flow.py` — тесты AI-кредитования
- `test_debt_system.py` — тесты системы долгов
- `tests/integration/` — интеграционные тесты с реальной БД

---

## 🔗 References

- Pytest docs: https://docs.pytest.org/
- `@bot/dice_check.py` (тестируемый код)
- `@bot/services/heist.py` (тестируемый код)
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 5)
