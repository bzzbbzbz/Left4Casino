# Быстрая проверка времени Happy Moment

## 1) Узнать расписание на сегодня (из логов планировщика)

```bash
rg -n "Generated happy moment schedule" /var/lib/docker/containers/*/*-json.log -S | tail -n 20
```

Ищите строку вида:

`"Generated happy moment schedule", "count": 2, "times": ["00:21", "20:44"]`

Это запланированные времена на текущие сутки в timezone бота (`reports.timezone`, сейчас `Asia/Yekaterinburg`).

## 2) Проверить, какие старты уже произошли сегодня (из БД)

```bash
python3 - <<'PY'
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

db = "telegram-casino-bot/bot/casino.db"
tz = ZoneInfo("Asia/Yekaterinburg")
today = datetime.now(timezone.utc).astimezone(tz).date()

conn = sqlite3.connect(db)
cur = conn.cursor()
rows = cur.execute("""
SELECT created_at, amount, metadata
FROM event_history
WHERE event_type='happy_moment_start'
ORDER BY created_at DESC
LIMIT 200
""").fetchall()

print("today =", today.isoformat())
for created_at, amount, metadata in rows:
    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(tz)
    if dt.date() == today:
        print(dt.strftime("%H:%M:%S"), "x", amount, metadata)
PY
```

Если в п.1 есть время, которого нет в п.2, значит это следующий (еще не начавшийся) счастливый миг.
