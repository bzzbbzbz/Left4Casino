# TASK-012: CI/CD Pipeline (GitHub Actions)

**ID**: TASK-012  
**Title**: Настройка автоматизации тестов и деплоя через GitHub Actions  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-012-1: Test automation workflow
Создать workflow для автоматического запуска тестов.

**Acceptance Criteria:**
- Файл `.github/workflows/test.yml` создан
- Тесты запускаются на каждый push в любую ветку
- Тесты запускаются на каждый pull request
- Unit и integration тесты запускаются параллельно (разные jobs)
- PR блокируется если тесты не проходят

### REQ-012-2: Linting workflow
Создать workflow для проверки качества кода.

**Acceptance Criteria:**
- Файл `.github/workflows/lint.yml` создан
- Запускается `ruff check` и `ruff format --check`
- Запускается `pyright` для проверки типов
- PR блокируется если есть lint errors

### REQ-012-3: Build and deploy workflow (optional)
Создать workflow для автоматического деплоя (при необходимости).

**Acceptance Criteria:**
- Файл `.github/workflows/deploy.yml` создан
- Билдится Docker образ при merge в main
- Образ публикуется в GitHub Container Registry (ghcr.io)
- Опционально: автоматический deploy на сервер через SSH

### REQ-012-4: Status badges
Добавить badges в README для отображения статуса CI.

**Acceptance Criteria:**
- Badge "Tests" показывает статус тестов
- Badge "Lint" показывает статус линтинга
- Badges кликабельны и ведут на Actions

---

## 🎯 Goals

**Primary Goal:**
Автоматизировать проверку качества кода и тестирование для предотвращения merge сломанного кода.

**Why This Matters:**
- **Quality Gate**: Сломанный код не попадёт в main ветку
- **Confidence**: Разработчики видят, что тесты прошли перед merge
- **Time Saving**: Не нужно вручную запускать тесты перед каждым коммитом
- **Documentation**: Status badges показывают состояние проекта

---

## 📐 Design

### Workflow Overview
```
┌─────────────────────────────────────────────────┐
│  Developer pushes code to branch                │
└────────────────┬────────────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │  GitHub Actions Trigger  │
    └────────┬────────┬────────┘
             │        │
   ┌─────────▼──┐  ┌─▼──────────┐
   │ Lint Job   │  │  Test Jobs  │
   │ - ruff     │  │  - unit     │
   │ - pyright  │  │  - integration │
   └─────────┬──┘  └─┬──────────┘
             │        │
    ┌────────▼────────▼────────┐
    │   All checks passed?     │
    └────────┬─────────────────┘
             │
      ┌──────▼──────┐
      │ ✓ Allow PR  │
      │   merge     │
      └─────────────┘
```

### .github/workflows/test.yml
```yaml
name: Tests

on:
  push:
    branches: ["**"]  # All branches
  pull_request:
    branches: [main]

jobs:
  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      
      - name: Run unit tests
        env:
          ENV: test
        run: |
          pytest tests/unit/ -v --cov=telegram-casino-bot/bot --cov-report=xml
      
      - name: Upload coverage to Codecov (optional)
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
          flags: unittests
  
  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      
      - name: Run integration tests
        env:
          ENV: test
        run: |
          pytest tests/integration/ -v
```

### .github/workflows/lint.yml
```yaml
name: Lint

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  ruff:
    name: Ruff (Linter + Formatter)
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      
      - name: Install ruff
        run: pip install ruff
      
      - name: Run ruff check
        run: ruff check .
      
      - name: Run ruff format check
        run: ruff format --check .
  
  pyright:
    name: Pyright (Type Checker)
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyright
      
      - name: Run pyright
        run: pyright
```

### .github/workflows/deploy.yml (Optional)
```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:  # Manual trigger

jobs:
  build-and-push:
    name: Build Docker Image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          target: prod
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:latest
            ghcr.io/${{ github.repository }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
  
  deploy:
    name: Deploy to Server
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/casino-bot
            docker compose pull
            docker compose up -d --no-deps --force-recreate casino-bot
            docker system prune -f
```

### Branch Protection Rules
```yaml
# Settings → Branches → Branch protection rules (main)

✓ Require a pull request before merging
  ✓ Require approvals: 1
✓ Require status checks to pass before merging
  Required checks:
    - Unit Tests
    - Integration Tests
    - Ruff (Linter + Formatter)
    - Pyright (Type Checker)
✓ Require branches to be up to date before merging
✓ Include administrators (optional)
```

### Status Badges (README.md)
```markdown
# Left4Casino Bot

[![Tests](https://github.com/USERNAME/REPO/actions/workflows/test.yml/badge.svg)](https://github.com/USERNAME/REPO/actions/workflows/test.yml)
[![Lint](https://github.com/USERNAME/REPO/actions/workflows/lint.yml/badge.svg)](https://github.com/USERNAME/REPO/actions/workflows/lint.yml)
[![codecov](https://codecov.io/gh/USERNAME/REPO/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/REPO)

Telegram casino bot with AI banker...
```

---

## ✅ Implementation Checklist

### Phase 1: GitHub Actions Setup
- [ ] Создать `.github/workflows/` директорию
- [ ] Создать `test.yml` с unit и integration jobs
- [ ] Создать `lint.yml` с ruff и pyright jobs
- [ ] Протестировать workflows на feature ветке

### Phase 2: Branch Protection
- [ ] Настроить branch protection для main
- [ ] Добавить required checks
- [ ] Протестировать: создать PR с failing test — должен блокироваться

### Phase 3: Deploy Workflow (Optional)
- [ ] Создать `deploy.yml` для Docker build
- [ ] Настроить GitHub Container Registry
- [ ] Добавить secrets: DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY
- [ ] Протестировать deploy на staging окружении

### Phase 4: Documentation
- [ ] Добавить status badges в README
- [ ] Обновить `AGENTS.md` (секция "CI/CD")
- [ ] Документировать процесс merge PR

---

## 🧪 Testing & Validation

### Manual Testing
```bash
# 1. Create test branch
git checkout -b test-ci-pipeline

# 2. Make a change that breaks tests
# (e.g., change dice_check logic)

# 3. Push to GitHub
git push origin test-ci-pipeline

# 4. Create PR to main
# → GitHub Actions should run
# → Tests should fail
# → PR should be blocked

# 5. Fix the code
git commit --amend
git push --force

# → Tests should pass
# → PR can be merged
```

### Success Metrics
- Tests run automatically on each push ✓
- Failed tests block PR merge ✓
- Status badges show green ✓
- Deploy workflow builds Docker image ✓

---

## 📦 Dependencies

**Before this task:**
- TASK-003 (ruff + pyright) — используются в lint workflow
- TASK-004 (tests) — используются в test workflow
- TASK-009 (Docker) — используется в deploy workflow (optional)

**After this task:**
- Защищает main ветку от сломанного кода
- Автоматизирует деплой

---

## 📝 Notes

### GitHub Actions Pricing
```
Free tier:
- Public repos: Unlimited minutes
- Private repos: 2000 minutes/month

Typical usage:
- Test workflow: ~5 min per run
- Lint workflow: ~2 min per run
→ ~400 runs per month in free tier
```

### Caching Strategy
```yaml
# Cache pip dependencies
- uses: actions/setup-python@v5
  with:
    cache: "pip"  # Speeds up by ~30 sec

# Cache Docker layers
cache-from: type=gha
cache-to: type=gha,mode=max
```

### Secrets Management
```bash
# Set secrets in GitHub:
# Settings → Secrets and variables → Actions

DEPLOY_HOST: server.example.com
DEPLOY_USER: deploy
DEPLOY_SSH_KEY: (paste private key)
OPENROUTER_API_KEY: sk-or-v1-...
BOT_TOKEN: 123456:ABC...
```

### Workflow Triggers
```yaml
on:
  push:
    branches: [main]       # Only on main
  pull_request:            # On any PR
  workflow_dispatch:       # Manual trigger
  schedule:
    - cron: '0 0 * * *'   # Daily at midnight
```

### Matrix Testing (Advanced)
```yaml
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
```

### Deploy via Webhook (Alternative)
```yaml
# Instead of SSH, use webhook
- name: Trigger deploy webhook
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }} \
      -H "Authorization: Bearer ${{ secrets.WEBHOOK_TOKEN }}"
```

---

## 🔗 References

- GitHub Actions docs: https://docs.github.com/en/actions
- Workflow syntax: https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions
- Docker publish: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 12)
