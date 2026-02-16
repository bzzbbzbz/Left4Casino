# TASK-009: Docker Multi-Stage Build

**ID**: TASK-009  
**Title**: Оптимизация Docker образа через multi-stage build  
**Priority**: MEDIUM  
**Status**: SPEC_READY  
**Created**: 2026-02-15  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-009-1: Multi-stage Dockerfile
Создать Dockerfile с multi-stage build для уменьшения размера образа.

**Acceptance Criteria:**
- Dockerfile содержит минимум 2 стадии: builder и final
- Builder стадия устанавливает зависимости
- Final стадия содержит только runtime код
- Размер final образа < 200 MB (currently ~500+ MB)

### REQ-009-2: Security improvements
Запускать контейнер под непривилегированным пользователем.

**Acceptance Criteria:**
- Создан непривилегированный пользователь `casino`
- Контейнер НЕ работает от root
- Файлы принадлежат `casino:casino`
- Порты > 1024 (если нужны)

### REQ-009-3: Layer caching optimization
Оптимизировать порядок инструкций для максимального переиспользования кеша.

**Acceptance Criteria:**
- `requirements.txt` копируется ДО копирования исходного кода
- Изменение кода не инвалидирует кеш установки зависимостей
- Rebuild времени < 30 секунд при изменении только Python кода

### REQ-009-4: Development and production targets
Создать отдельные targets для dev и prod.

**Acceptance Criteria:**
- Target `dev` с установленными dev-зависимостями и монтированным кодом
- Target `prod` с минимальными зависимостями и копированным кодом
- Можно собрать: `docker build --target dev` или `--target prod`

---

## 🎯 Goals

**Primary Goal:**
Уменьшить размер Docker образа и улучшить безопасность через best practices.

**Why This Matters:**
- **Faster Deploys**: Меньше образ = меньше времени на скачивание/загрузку
- **Security**: Контейнер без root снижает риск escalation
- **Cost**: Меньше трафика и storage
- **Build Time**: Правильный кеш ускоряет rebuilds в 10-20 раз

---

## 📐 Design

### Current vs Optimized
| Metric | Current | Optimized | Improvement |
|--------|---------|-----------|-------------|
| **Image Size** | ~500 MB | < 200 MB | 60% reduction |
| **Build Time (full)** | 5 min | 2 min | 60% faster |
| **Build Time (code change)** | 5 min | 30 sec | 90% faster |
| **Security** | root user | unprivileged | ✓ hardened |
| **Layers** | Many | Optimized | Better caching |

### Multi-Stage Dockerfile
```dockerfile
# ============================================================
# Stage 1: Builder - Install dependencies
# ============================================================
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: Development - With dev tools
# ============================================================
FROM python:3.11-slim AS dev

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dev dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir pytest pytest-asyncio ruff pyright

WORKDIR /app

# Don't copy code - will be mounted as volume
# docker run -v $(pwd):/app ...

CMD ["python", "main.py"]

# ============================================================
# Stage 3: Production - Minimal final image
# ============================================================
FROM python:3.11-slim AS prod

# Install only runtime dependencies (if any)
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create unprivileged user
RUN useradd -m -u 1000 casino && \
    mkdir -p /app /data && \
    chown -R casino:casino /app /data

# Set working directory
WORKDIR /app

# Copy application code (only what's needed)
COPY --chown=casino:casino main.py .
COPY --chown=casino:casino telegram-casino-bot/ telegram-casino-bot/
COPY --chown=casino:casino groups.json .

# Switch to unprivileged user
USER casino

# Health check (optional)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('/data/casino.db').close()" || exit 1

# Run bot
CMD ["python", "main.py"]
```

### .dockerignore
```
# .dockerignore - Exclude unnecessary files from build context

# Git
.git/
.gitignore

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/

# Virtual environments
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Tests
tests/
pytest_cache/

# Documentation
docs/
*.md
!README.md

# Configs (will be provided at runtime)
config/settings.prod.toml
*.db
*.log

# CI/CD
.github/
.gitlab-ci.yml

# Temp files
*.tmp
*.bak
```

### docker-compose.yml (Updated)
```yaml
version: "3.8"

services:
  # Development service
  casino-bot-dev:
    build:
      context: .
      target: dev
    volumes:
      - .:/app  # Mount code for hot reload
      - bot_data:/data
    environment:
      - ENV=dev
      - CONFIG_FILE_PATH=/app/config/settings.dev.toml
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    restart: unless-stopped
    profiles:
      - dev
  
  # Production service
  casino-bot:
    build:
      context: .
      target: prod
    volumes:
      - bot_data:/data  # Only data, not code
      - ./config:/app/config:ro  # Read-only config
    environment:
      - ENV=prod
      - CONFIG_FILE_PATH=/app/config/settings.prod.toml
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - BOT_TOKEN=${BOT_TOKEN}
      - REDIS_DSN=${REDIS_DSN}
    restart: unless-stopped
    depends_on:
      - redis
    profiles:
      - prod
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped
    profiles:
      - prod

volumes:
  bot_data:
  redis_data:
```

### Build and Run Commands
```bash
# Build development image
docker build --target dev -t casino-bot:dev .

# Build production image
docker build --target prod -t casino-bot:prod .

# Run development (with code mount)
docker-compose --profile dev up

# Run production
docker-compose --profile prod up -d

# Check image sizes
docker images | grep casino-bot
```

---

## ✅ Implementation Checklist

### Phase 1: Dockerfile Optimization
- [ ] Создать multi-stage Dockerfile с 3 стадиями
- [ ] Оптимизировать порядок COPY для кеширования
- [ ] Создать непривилегированного пользователя
- [ ] Добавить HEALTHCHECK

### Phase 2: .dockerignore
- [ ] Создать `.dockerignore` для исключения ненужных файлов
- [ ] Проверить размер build context: `docker build --no-cache 2>&1 | grep "Sending build context"`

### Phase 3: docker-compose
- [ ] Обновить `docker-compose.yml` с dev и prod профилями
- [ ] Настроить volumes для данных
- [ ] Добавить environment variables

### Phase 4: Testing
- [ ] Собрать dev образ и протестировать hot reload
- [ ] Собрать prod образ и проверить размер
- [ ] Протестировать healthcheck: `docker inspect --format='{{.State.Health.Status}}' <container>`

### Phase 5: Documentation
- [ ] Обновить `AGENTS.md` (секция "Docker")
- [ ] Создать `docs/DOCKER_GUIDE.md` с инструкциями
- [ ] Документировать команды сборки и деплоя

---

## 🧪 Testing & Validation

### Build and Verify
```bash
# 1. Full build (no cache)
time docker build --no-cache --target prod -t casino-bot:prod .
# Should complete in < 3 min

# 2. Rebuild after code change
echo "# test" >> main.py
time docker build --target prod -t casino-bot:prod .
# Should complete in < 30 sec (using cache)

# 3. Check image size
docker images casino-bot:prod
# Should be < 200 MB

# 4. Check layers
docker history casino-bot:prod
# Should have ~10-15 layers
```

### Security Check
```bash
# Check user
docker run --rm casino-bot:prod whoami
# Should output: casino (not root)

# Check file permissions
docker run --rm casino-bot:prod ls -la /app
# Should show owner: casino
```

### Runtime Test
```bash
# Run production container
docker run -d \
  --name casino-test \
  -e ENV=prod \
  -e BOT_TOKEN=test:token \
  -v $(pwd)/config:/app/config:ro \
  casino-bot:prod

# Check logs
docker logs casino-test
# Should show "Running in PROD mode"

# Check health
docker inspect --format='{{.State.Health.Status}}' casino-test
# Should output: healthy

# Cleanup
docker stop casino-test && docker rm casino-test
```

### Success Metrics
- Image size < 200 MB ✓
- Build from cache < 30 sec ✓
- Runs as non-root ✓
- Healthcheck passes ✓

---

## 📦 Dependencies

**Before this task:**
- Существующий Dockerfile (будет заменён)
- `requirements.txt` актуален

**After this task:**
- Используется для деплоя в продакшн
- Уменьшает время CI/CD

---

## 📝 Notes

### Why Multi-Stage?
```
Stage 1 (builder): 800 MB (with gcc, build tools)
↓ copy venv only
Stage 2 (final): 180 MB (only runtime + code)
```

### Layer Caching Best Practices
```dockerfile
# ✅ GOOD: Dependencies cached separately
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# ❌ BAD: Code changes invalidate pip install
COPY . .
RUN pip install -r requirements.txt
```

### Security Best Practices
```dockerfile
# ✅ GOOD
USER casino

# ❌ BAD (CVE risk)
USER root
```

### Health Check
Проверяет доступность БД (бот жив):
```bash
docker inspect --format='{{.State.Health.Status}}' <container>
# healthy | unhealthy | starting
```

### Build Cache
Docker кеширует каждую инструкцию:
```
Step 5/20 : RUN pip install -r requirements.txt
---> Using cache  ← 5 seconds вместо 60!
```

---

## 🔗 References

- Docker best practices: https://docs.docker.com/develop/dev-best-practices/
- Multi-stage builds: https://docs.docker.com/build/building/multi-stage/
- `@docs/PROJECT_IMPROVEMENTS.md` (секция 9)
- Current Dockerfile (will be replaced)
