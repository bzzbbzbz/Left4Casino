# TASK-011: Semantic Regions for Critical Code

**ID**: TASK-011  
**Title**: Разметка критичного кода семантическими регионами  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-011-1: Semantic regions format
Определить единый формат семантических регионов для проекта.

**Acceptance Criteria:**
- Создан документ `docs/SEMANTIC_REGIONS_GUIDE.md` с форматом
- Формат включает: SPEC_ID, FUNCTION_NAME, REQ, SOURCE
- Примеры для всех типичных случаев (функции, классы, блоки)
- Документирован в `AGENTS.md` и `.cursorrules`

### REQ-011-2: Critical files markup
Разметить 4-5 критичных файлов с game balance логикой.

**Acceptance Criteria (High Priority):**
- ✅ `bot/dice_check.py` — 100% критичных функций размечено
- ✅ `bot/services/heist.py` — экономические методы размечены (calculate_pot_cap, calculate_commission, transition_to_phase_2)
- ✅ `bot/db.py` — атомарные транзакции размечены (transfer_money, safe_deposit, safe_withdraw)
- ✅ `bot/handlers/dice_fight.py` — система долгов размечена (resolve_challenge, взаимозачёт)

**Acceptance Criteria (Medium Priority - optional):**
- `bot/services/ai.py` — эвристика AI-генерации
- `bot/services/happy_moment.py` — расчёт множителей

### REQ-011-3: Verification tool
Создать скрипт для проверки соответствия кода и спецификаций.

**Acceptance Criteria:**
- Создан `scripts/verify_regions.py`
- Скрипт парсит маркеры `[START SPEC:...]` из кода
- Скрипт проверяет существование REQ-ID в спецификациях
- Генерирует отчёт о несоответствиях
- Можно запустить в pre-commit (опционально)

### REQ-011-4: Documentation and workflow
Интегрировать разметку в workflow разработки.

**Acceptance Criteria:**
- `.cursorrules` обновлён с инструкциями для AI
- `AGENTS.md` содержит секцию "Semantic Regions"
- В `skill:code` протоколе упомянута обязательная разметка
- Template для новых функций добавлен в docs/

---

## 🎯 Goals

**Primary Goal:**
Добавить семантическую разметку в критичный код для предотвращения случайных изменений AI и упрощения навигации.

**Why This Matters:**
- **AI Navigation**: Cursor видит границы логических блоков и не трогает чужие регионы
- **Traceability**: Понятно, какой код относится к какому REQ из спецификации
- **Refactoring Safety**: При изменениях видно, что может сломать game balance
- **Knowledge Transfer**: Новые разработчики быстро находят реализацию требований

---

## 📐 Design

### Semantic Regions Format

#### Basic Format
```python
# [START SPEC:{SPEC_ID}:{REGION_NAME}]
# REQ: {Brief requirement description}
# Source: {SPEC_FILE.md, section name}
# CRITICAL: {Optional warning about what NOT to change}

def critical_function():
    """Docstring as usual."""
    # Implementation
    pass

# [END SPEC:{SPEC_ID}]
```

#### SPEC_ID Conventions
```
Format: {FEATURE}-{ASPECT}

Examples:
- HEIST-ECONOMY         → Heist economic calculations
- HEIST-PHASES          → Heist phase transitions
- DICE-BALANCE          → Dice win calculation (game balance)
- SAFE-ATOMIC           → Safe atomic transactions
- AI-CREDIT-EVAL        → AI credit evaluation logic
- DEBT-SETTLEMENT       → Debt mutual settlement
- TASK-XXX              → New code from specifications
```

#### Region Types

**1. Function/Method Region**
```python
# [START SPEC:HEIST-ECONOMY:calculate_pot_cap]
# REQ: pot_cap = base_winnings * 5%
# Source: HEIST_SPEC.md, "Экономика"
# CRITICAL: Don't change multiplier without game balance review
def calculate_pot_cap(self, base_winnings: int) -> int:
    """Calculate maximum pot size."""
    if base_winnings < 1000:
        base_winnings = 1000  # Fallback
    return int(base_winnings * self.pot_cap_multiplier)
# [END SPEC:HEIST-ECONOMY]
```

**2. Class Region (multiple methods)**
```python
# [START SPEC:DICE-BALANCE:SlotCombinations]
# REQ: Map dice values 1-64 to slot combinations
# Source: DICE_CHECK.py docstring, original implementation
class SlotMachine:
    """Slot machine logic."""
    
    def get_combination(self, dice_value: int) -> tuple:
        """Map dice to slot symbols."""
        # ... implementation ...
    
    def calculate_score(self, combination: tuple) -> int:
        """Calculate win/loss from combination."""
        # CRITICAL: Changing these values affects game balance
        if combination == (7, 7, 7):
            return 10  # Jackpot
        # ... more logic ...
# [END SPEC:DICE-BALANCE]
```

**3. Code Block Region (within function)**
```python
def resolve_challenge(self, challenge_id: int):
    """Resolve dice challenge."""
    
    # [START SPEC:DEBT-SETTLEMENT:Mutual Offset]
    # REQ: If A owes B and B owes A, debts cancel out
    # Source: DICE_FIGHT_SPEC.md, "Взаимозачёт долгов"
    if existing_debt_from_opponent:
        offset_amount = min(debt_to_create, existing_debt_from_opponent)
        await self.reduce_debt(opponent_id, challenger_id, offset_amount)
        debt_to_create -= offset_amount
    # [END SPEC:DEBT-SETTLEMENT]
    
    # ... rest of function ...
```

---

## 📝 Priority Matrix

### 🔴 High Priority (MUST mark)

| File | Functions/Methods | Reason |
|------|-------------------|--------|
| `bot/dice_check.py` | `get_slot_combination()`, `calculate_base_score()` | Game balance — легко сломать случайным изменением |
| `bot/services/heist.py` | `calculate_pot_cap()`, `calculate_commission()`, `transition_to_phase_2()` | Экономика — влияет на инфляцию/дефляцию |
| `bot/db.py` | `transfer_money()`, `safe_deposit()`, `safe_withdraw()` | Атомарность — ACID transactions критичны |
| `bot/handlers/dice_fight.py` | `resolve_challenge()` (debt settlement block) | Взаимозачёт — сложная логика с edge cases |

### 🟡 Medium Priority (SHOULD mark)

| File | Functions/Methods | Reason |
|------|-------------------|--------|
| `bot/services/ai.py` | `generate_response()` (AI detection heuristics) | Эвристика — тонко настроенные пороги |
| `bot/services/happy_moment.py` | `get_multiplier_for_duration()` | Множители — влияют на game balance |
| `bot/services/heist.py` | `_trigger_seed()`, phase timers | Fallback логика — важна для UX |

### 🟢 Low Priority (NICE to mark)

| File | Functions/Methods | Reason |
|------|-------------------|--------|
| Handlers | Command logic | Обычно простая бизнес-логика без сложных алгоритмов |
| Middlewares | Throttling, logging | Utility код, легко понять без маркеров |

---

## ✅ Implementation Checklist

### Phase 1: Documentation (1 час)
- [ ] Создать `docs/SEMANTIC_REGIONS_GUIDE.md` с примерами
- [ ] Обновить `.cursorrules` с инструкциями для AI
- [ ] Обновить `AGENTS.md` (секция "Semantic Regions")
- [ ] Добавить template в `docs/templates/function_with_region.py`

### Phase 2: High Priority Files (3 часа)
- [ ] Разметить `bot/dice_check.py` (2-3 функции)
  - [ ] `get_slot_combination()`
  - [ ] `calculate_base_score()`
  - [ ] Win probability constants
- [ ] Разметить `bot/services/heist.py` (4-5 методов)
  - [ ] `calculate_pot_cap()`
  - [ ] `calculate_commission()`
  - [ ] `transition_to_phase_2()`
  - [ ] `_trigger_seed()` (fallback логика)
- [ ] Разметить `bot/db.py` (3 метода)
  - [ ] `transfer_money()`
  - [ ] `safe_deposit()`
  - [ ] `safe_withdraw()`
- [ ] Разметить `bot/handlers/dice_fight.py` (1 блок)
  - [ ] `resolve_challenge()` — debt settlement block

### Phase 3: Verification Tool (2 часа)
- [ ] Создать `scripts/verify_regions.py`
- [ ] Парсинг маркеров из Python файлов (regex)
- [ ] Проверка существования SPEC_ID в docs/specs/
- [ ] Генерация отчёта (markdown table)
- [ ] Добавить в pre-commit (опционально)

### Phase 4: Medium Priority (опционально, 1 час)
- [ ] Разметить `bot/services/ai.py`
- [ ] Разметить `bot/services/happy_moment.py`

### Phase 5: Testing
- [ ] Запустить `scripts/verify_regions.py`
- [ ] Проверить, что AI не предлагает изменения внутри критичных регионов (manual test)
- [ ] Убедиться, что маркеры не ломают синтаксис Python

---

## 🧪 Testing & Validation

### Manual Testing

**Test 1: AI Navigation**
```
1. Открыть файл bot/dice_check.py в Cursor
2. Попросить AI: "Improve performance of this file"
3. Ожидание: AI НЕ предлагает изменения в [START SPEC] регионах
4. AI комментирует: "Skipping dice balance logic (marked as critical)"
```

**Test 2: Traceability**
```
1. Найти маркер: # [START SPEC:HEIST-ECONOMY:calculate_pot_cap]
2. Открыть Source: HEIST_SPEC.md
3. Проверить, что REQ соответствует спецификации
```

**Test 3: Verification Script**
```bash
# Run verification
python scripts/verify_regions.py

# Expected output:
✓ Found 12 semantic regions
✓ All SPEC_IDs have corresponding specs
⚠ Warning: DICE-BALANCE region references non-existent REQ-042
```

### Success Metrics
- Все High Priority файлы размечены (4 файла)
- Verification script находит все маркеры
- Маркеры не ломают синтаксис (ruff check проходит)
- AI учитывает маркеры при рефакторинге (manual test)

---

## 📦 Dependencies

**Before this task:**
- Существующий код работает (не ломаем ничего)
- Спецификации в `docs/specs/` существуют (для cross-reference)

**After this task:**
- Используется в `skill:code` протоколе (AGENTS.md)
- Используется при реализации TASK-001 и далее
- Упрощает code review и onboarding

---

## 📝 Notes

### When to Add Regions?

**✅ ALWAYS add for:**
- Game balance calculations (win rates, multipliers, pot caps)
- Atomic transactions (money transfers, safe operations)
- Complex algorithms with edge cases (debt settlement)
- New code from TASK-001+ specifications

**⚠️ CONSIDER adding for:**
- Business logic that changes frequently
- Code touched during refactoring
- Functions with non-obvious requirements

**❌ SKIP for:**
- Simple CRUD operations
- Utility functions (formatters, validators)
- Middleware and decorators
- One-liners and constants

### Region Naming Best Practices

```python
# ✅ GOOD: Specific, describes what the code does
# [START SPEC:HEIST-ECONOMY:calculate_pot_cap]

# ❌ BAD: Too generic
# [START SPEC:HEIST:method1]

# ✅ GOOD: References specific requirement
# REQ: pot_cap = base_winnings * 5%

# ❌ BAD: No connection to spec
# REQ: Calculate something
```

### Integration with .cursorrules

Add to `.cursorrules`:
```
## Semantic Regions

When encountering code with `[START SPEC:...]` markers:
1. READ the REQ and Source comments
2. DO NOT modify code inside regions without explicit user request
3. If asked to refactor, mention: "This region is marked as critical (SPEC_ID)"
4. When writing NEW code from specifications, ALWAYS add semantic regions

Format:
# [START SPEC:{SPEC_ID}:{NAME}]
# REQ: {requirement}
# Source: {spec file}
{code}
# [END SPEC:{SPEC_ID}]
```

### Verification Script Design

```python
# scripts/verify_regions.py
import re
from pathlib import Path

def find_regions(file_path):
    """Find all [START SPEC:...] markers in file."""
    pattern = r'# \[START SPEC:([A-Z\-]+):([^\]]+)\]'
    with open(file_path) as f:
        content = f.read()
    return re.findall(pattern, content)

def verify_spec_exists(spec_id):
    """Check if SPEC_ID exists in docs/specs/."""
    # Check if spec_id mentioned in any spec file
    specs_dir = Path("docs/specs")
    for spec_file in specs_dir.glob("*.md"):
        if spec_id in spec_file.read_text():
            return True
    return False

# Main logic
regions = []
for py_file in Path("telegram-casino-bot/bot").rglob("*.py"):
    regions.extend(find_regions(py_file))

print(f"Found {len(regions)} semantic regions")
# ... validation logic ...
```

---

## 🔗 References

- `@AGENTS.md` (Workflow Lifecycle, skill:code)
- `@.cursorrules` (will be updated)
- `@docs/specs/HEIST_SPEC.md` (example of spec to reference)
- `@bot/services/heist.py` (example file to markup)

---

## 📄 Example: Before and After

### Before (no regions)
```python
def calculate_pot_cap(self, base_winnings: int) -> int:
    """Calculate maximum pot size."""
    if base_winnings < 1000:
        base_winnings = 1000
    return int(base_winnings * self.pot_cap_multiplier)
```

### After (with region)
```python
# [START SPEC:HEIST-ECONOMY:calculate_pot_cap]
# REQ: pot_cap = base_winnings * 5% (с fallback к 1000)
# Source: HEIST_SPEC.md, секция "Экономика"
# CRITICAL: Multiplier влияет на длительность ивента и game balance
def calculate_pot_cap(self, base_winnings: int) -> int:
    """
    Рассчитать максимальный размер банка.
    
    При достижении pot_cap происходит досрочный переход в Фазу 2.
    Если изменить multiplier:
    - Больше → дольше Фаза 1 → больше участников
    - Меньше → быстрее переход → меньше риск
    """
    if base_winnings < 1000:
        base_winnings = 1000  # Fallback для новых чатов
    return int(base_winnings * self.pot_cap_multiplier)
# [END SPEC:HEIST-ECONOMY]
```

---

**Status**: SPEC_READY  
**Estimated time**: 5-7 hours total  
**Priority**: MEDIUM (но HIGH для game balance кода)
