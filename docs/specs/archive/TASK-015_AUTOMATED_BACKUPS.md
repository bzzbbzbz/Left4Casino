# TASK-015: Automated Daily Backups

**ID**: TASK-015  
**Title**: Автоматическое создание и отправка бэкапов в Telegram  
**Priority**: HIGH  
**Status**: DONE  
**Created**: 2026-02-16  
**Assignee**: cursor-agent

---

## 📋 Requirements

### REQ-015-1: Создание бэкапов в 00:00
Ежедневно в 00:00 (по timezone из конфига) создавать архив с критичными файлами.

**Acceptance Criteria:**
- Бэкап создаётся автоматически через APScheduler в 00:00
- Архив содержит:
  - `bot/casino.db` — база данных
  - `settings.toml` — конфигурация бота
  - `groups.json` — список групп
- Формат архива: `backup_YYYYMMDD_HHMMSS.tar.gz`
- Архив сохраняется во временную директорию `/tmp/casino_backups/`
- Используется timezone из `[reports].timezone` в settings.toml

### REQ-015-2: Отправка бэкапа админу
После создания архива отправить его в Telegram админу.

**Acceptance Criteria:**
- Бэкап отправляется как document (файл) в Telegram
- Получатель: `admin_id` из `[reports]` секции settings.toml
- Сообщение содержит:
  - Дату и время создания бэкапа
  - Размер архива
  - Список включённых файлов
- Если `admin_id = 0` или не указан — бэкап не отправляется (только создаётся локально)

### REQ-015-3: Ротация старых бэкапов
Автоматически удалять старые бэкапы для экономии места.

**Acceptance Criteria:**
- Хранить только последние N бэкапов (N = 7 по умолчанию)
- Удаление происходит после создания нового бэкапа
- Ротация применяется к `/tmp/casino_backups/`

### REQ-015-4: Обработка ошибок
Graceful handling ошибок при создании и отправке бэкапов.

**Acceptance Criteria:**
- Если файл не найден (например, settings.toml отсутствует) — пропустить его, но продолжить бэкап
- Если не удалось создать архив — залогировать ошибку, не крашить бота
- Если не удалось отправить в Telegram — залогировать ошибку, архив остаётся локально
- Все ошибки логируются через structlog с уровнем ERROR

---

## 🎯 Goals

**Primary Goal:**
Автоматизировать создание бэкапов критичных данных и обеспечить их доступность для восстановления.

**Why This Matters:**
- **Disaster Recovery**: Быстрое восстановление после сбоя сервера или повреждения БД
- **Human Error Protection**: Защита от случайного удаления данных
- **Audit Trail**: История состояния бота на каждый день
- **Peace of Mind**: Админ получает ежедневное подтверждение работоспособности системы

**Use Cases:**
1. Сервер упал, нужно восстановить БД на новом сервере → скачать последний бэкап из Telegram
2. Случайно удалили `settings.toml` → восстановить из бэкапа
3. Нужно откатиться к состоянию 3 дня назад → найти соответствующий архив в Telegram

---

## 📐 Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    APScheduler (00:00)                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│               BackupService.create_backup()                  │
│  1. Создать /tmp/casino_backups/backup_YYYYMMDD_HHMMSS.tar.gz │
│  2. Добавить: casino.db, settings.toml, groups.json         │
│  3. Вернуть путь к архиву                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            BackupService.send_to_admin(backup_path)          │
│  1. Получить admin_id из конфига                            │
│  2. Отправить файл через bot.send_document()                │
│  3. Добавить caption с метаданными                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            BackupService.rotate_old_backups()                │
│  1. Получить список всех backup_*.tar.gz                    │
│  2. Отсортировать по дате                                    │
│  3. Удалить все, кроме последних 7                           │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
bot/
└── services/
    └── backup.py              # BackupService

/tmp/casino_backups/           # Временная директория для архивов
├── backup_20260216_000001.tar.gz
├── backup_20260215_000001.tar.gz
└── ...
```

### Configuration

Добавить новую секцию в `settings.toml`:

```toml
[backups]
# Enable/disable automated backups
enabled = true
# Number of backups to keep locally (older ones are deleted)
retention_days = 7
# Backup directory (default: /tmp/casino_backups)
backup_dir = "/tmp/casino_backups"
```

### API Design

#### BackupService

```python
class BackupService:
    def __init__(
        self,
        db_path: str,
        settings_path: str,
        groups_path: str,
        backup_dir: str,
        retention_days: int,
        bot: Bot,
        admin_id: int,
    ):
        """Initialize backup service"""
        
    async def create_backup(self) -> str | None:
        """
        Create a backup archive with all critical files.
        
        Returns:
            Path to created archive, or None if failed
        """
        
    async def send_to_admin(self, backup_path: str) -> bool:
        """
        Send backup file to admin via Telegram.
        
        Args:
            backup_path: Path to backup archive
            
        Returns:
            True if sent successfully, False otherwise
        """
        
    async def rotate_old_backups(self) -> int:
        """
        Remove old backups, keeping only last N.
        
        Returns:
            Number of deleted backups
        """
        
    async def run_backup(self) -> None:
        """
        Full backup workflow: create → send → rotate.
        Called by scheduler.
        """
```

### Scheduler Integration

В `bot/__main__.py`:

```python
# Backup scheduler job
async def run_daily_backup():
    """Create and send daily backup (called at 00:00)"""
    if backups_config.enabled:
        await backup_service.run_backup()

scheduler.add_job(run_daily_backup, "cron", hour=0, minute=0, timezone=timezone)
```

### Telegram Message Format

```
📦 Ежедневный бэкап

🗓 Дата: 16.02.2026 00:00:01
📊 Размер: 11.2 MB
📁 Файлы:
  ✅ bot/casino.db (11.0 MB)
  ✅ settings.toml (3.3 KB)
  ✅ groups.json (101 B)

💾 Архив: backup_20260216_000001.tar.gz
```

Если файл отсутствует:

```
📦 Ежедневный бэкап

🗓 Дата: 16.02.2026 00:00:01
📊 Размер: 11.0 MB
📁 Файлы:
  ✅ bot/casino.db (11.0 MB)
  ⚠️ settings.toml (не найден)
  ✅ groups.json (101 B)

💾 Архив: backup_20260216_000001.tar.gz
```

---

## ✅ Implementation Checklist

### Phase 1: Core Backup Service
- [x] Создать `bot/services/backup.py`
- [x] Реализовать `BackupService` класс
- [x] Реализовать `create_backup()` — создание tar.gz архива
- [x] Реализовать `send_to_admin()` — отправка в Telegram
- [x] Реализовать `rotate_old_backups()` — удаление старых бэкапов
- [x] Реализовать `run_backup()` — полный workflow

### Phase 2: Configuration
- [x] Добавить `[backups]` секцию в `settings.example.toml`
- [x] Добавить Pydantic модель `BackupsConfig` в `bot/models/config.py`
- [x] Обновить `bot/config_reader.py` для чтения `[backups]`

### Phase 3: Scheduler Integration
- [x] Добавить `run_daily_backup()` в `bot/__main__.py`
- [x] Зарегистрировать job в scheduler (00:00)
- [x] Передать `backup_service` в контекст

### Phase 4: Error Handling
- [x] Добавить try/except для каждого файла при архивации
- [x] Логировать ошибки через structlog
- [x] Graceful degradation: если один файл недоступен, продолжить с остальными

### Phase 5: Testing
- [x] Unit-тест: создание архива с mock-файлами
- [x] Unit-тест: ротация старых бэкапов
- [x] Integration-тест: отправка в Telegram (mock bot)
- [ ] Manual test: проверить реальную отправку админу (не выполнялся без обращения к production runtime)

---

## 🧪 Testing & Validation

### Unit Tests

**Test: `test_create_backup_success`**
```python
async def test_create_backup_success(tmp_path):
    """Test successful backup creation"""
    # Setup: create mock files
    db_path = tmp_path / "casino.db"
    db_path.write_bytes(b"fake db content")
    
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text("[bot]\ntoken = 'test'")
    
    groups_path = tmp_path / "groups.json"
    groups_path.write_text('{"123": "test"}')
    
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    
    # Execute
    service = BackupService(
        db_path=str(db_path),
        settings_path=str(settings_path),
        groups_path=str(groups_path),
        backup_dir=str(backup_dir),
        retention_days=7,
        bot=Mock(),
        admin_id=123,
    )
    
    backup_path = await service.create_backup()
    
    # Assert
    assert backup_path is not None
    assert Path(backup_path).exists()
    assert backup_path.endswith(".tar.gz")
    
    # Verify archive contents
    import tarfile
    with tarfile.open(backup_path, "r:gz") as tar:
        names = tar.getnames()
        assert "casino.db" in names
        assert "settings.toml" in names
        assert "groups.json" in names
```

**Test: `test_rotate_old_backups`**
```python
async def test_rotate_old_backups(tmp_path):
    """Test that old backups are deleted"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    
    # Create 10 fake backups
    for i in range(10):
        backup_file = backup_dir / f"backup_2026021{i:02d}_000000.tar.gz"
        backup_file.write_bytes(b"fake backup")
    
    service = BackupService(
        db_path="",
        settings_path="",
        groups_path="",
        backup_dir=str(backup_dir),
        retention_days=7,
        bot=Mock(),
        admin_id=123,
    )
    
    deleted = await service.rotate_old_backups()
    
    # Should delete 3 oldest backups (10 - 7 = 3)
    assert deleted == 3
    assert len(list(backup_dir.glob("*.tar.gz"))) == 7
```

**Test: `test_send_to_admin_disabled`**
```python
async def test_send_to_admin_disabled():
    """Test that backup is not sent if admin_id = 0"""
    service = BackupService(
        db_path="",
        settings_path="",
        groups_path="",
        backup_dir="/tmp",
        retention_days=7,
        bot=Mock(),
        admin_id=0,  # Disabled
    )
    
    result = await service.send_to_admin("/tmp/backup.tar.gz")
    
    # Should return False without calling bot.send_document
    assert result is False
```

### Integration Tests

**Test: `test_backup_workflow_end_to_end`**
```python
@pytest.mark.integration
async def test_backup_workflow_end_to_end(tmp_path, mock_bot):
    """Test full backup workflow"""
    # Setup real files
    db_path = tmp_path / "casino.db"
    db_path.write_bytes(b"x" * 1024)  # 1KB fake DB
    
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text("[bot]\ntoken = 'test'")
    
    groups_path = tmp_path / "groups.json"
    groups_path.write_text('{}')
    
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    
    service = BackupService(
        db_path=str(db_path),
        settings_path=str(settings_path),
        groups_path=str(groups_path),
        backup_dir=str(backup_dir),
        retention_days=7,
        bot=mock_bot,
        admin_id=123456,
    )
    
    # Execute full workflow
    await service.run_backup()
    
    # Assert: backup created
    backups = list(backup_dir.glob("*.tar.gz"))
    assert len(backups) == 1
    
    # Assert: bot.send_document was called
    mock_bot.send_document.assert_called_once()
    call_args = mock_bot.send_document.call_args
    assert call_args.kwargs["chat_id"] == 123456
    assert "backup_" in call_args.kwargs["caption"]
```

### Manual Testing Checklist

- [ ] Запустить бота с `[backups].enabled = true`
- [ ] Подождать 00:00 или вручную вызвать `run_daily_backup()`
- [ ] Проверить, что архив создан в `/tmp/casino_backups/`
- [ ] Проверить, что админ получил файл в Telegram
- [ ] Проверить формат сообщения (дата, размер, список файлов)
- [ ] Создать 10 бэкапов и проверить, что остаются только последние 7
- [ ] Удалить `settings.toml` и проверить, что бэкап создаётся без него (с предупреждением)
- [ ] Установить `admin_id = 0` и проверить, что бэкап создаётся, но не отправляется

---

## 🔧 Technical Considerations

### Security
- **Secrets in Backup**: `settings.toml` содержит bot token и API keys
  - ⚠️ Бэкап отправляется только админу (не в группы)
  - ⚠️ Рекомендация: использовать Secret Chat в Telegram для отправки бэкапов (будущее улучшение)
  - ⚠️ Альтернатива: шифровать архив паролем (будущее улучшение)

### Performance
- **Backup Size**: ~11 MB для текущей БД
  - Telegram поддерживает файлы до 2 GB → не проблема
  - Архивация занимает ~1-2 секунды → не блокирует бота (async)

### Disk Space
- **Retention**: 7 дней × 11 MB = ~77 MB
  - Приемлемо для `/tmp` (обычно несколько GB)
  - При необходимости можно уменьшить `retention_days`

### Failure Modes
1. **Disk Full**: Если `/tmp` заполнен → логировать ошибку, пропустить бэкап
2. **Telegram API Error**: Если не удалось отправить → архив остаётся локально
3. **Missing Files**: Если файл не найден → пропустить, продолжить с остальными

---

## 📚 References

- **Related Files**:
  - `bot/__main__.py` — scheduler setup
  - `bot/services/daily_stats.py` — пример сервиса с отправкой в Telegram
  - `settings.toml` — конфигурация
  
- **Related Tasks**:
  - TASK-007: Database Migrations System (миграции БД)
  - TASK-014: Schedule Visibility (планировщик)

- **External Docs**:
  - [APScheduler CronTrigger](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html)
  - [Python tarfile](https://docs.python.org/3/library/tarfile.html)
  - [aiogram send_document](https://docs.aiogram.dev/en/latest/api/methods/send_document.html)

---

## 💡 Future Enhancements

### Phase 2 (Optional)
- [ ] Шифрование архива паролем (AES-256)
- [ ] Отправка в несколько каналов (резервное хранилище)
- [ ] Webhook для уведомления о бэкапе (например, в Discord/Slack)
- [ ] Автоматическое восстановление из бэкапа (команда `/restore`)

### Phase 3 (Advanced)
- [ ] Инкрементальные бэкапы (только изменения)
- [ ] Загрузка в облачное хранилище (S3, Google Drive)
- [ ] Мониторинг размера БД и алерты при аномальном росте
- [ ] Бэкап логов и event_history (опционально)

---

**Status**: Ready for Implementation  
**Estimated Effort**: 4-6 hours  
**Risk Level**: Low (изолированная функциональность, не влияет на игровую логику)
