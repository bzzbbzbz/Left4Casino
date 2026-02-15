import asyncio
import json
from pathlib import Path

GROUPS_FILE = Path("groups.json")


def _read_groups_sync() -> dict[str, str]:
    if not GROUPS_FILE.exists():
        return {}
    try:
        with open(GROUPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_group_sync(chat_id: int, title: str):
    groups = _read_groups_sync()
    str_id = str(chat_id)

    # Only write if new or title changed
    if str_id not in groups or groups[str_id] != title:
        groups[str_id] = title
        with open(GROUPS_FILE, mode="w", encoding="utf-8") as f:
            json.dump(groups, f, indent=2, ensure_ascii=False)


async def load_groups() -> dict[str, str]:
    return await asyncio.to_thread(_read_groups_sync)


async def save_group(chat_id: int, title: str):
    await asyncio.to_thread(_save_group_sync, chat_id, title)
