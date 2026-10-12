"""Сохранение заявок в CSV-файл."""
import csv
import os
import re
from datetime import datetime

FIELDS = ["datetime", "vk_id", "name", "contact"]


TG_HANDLE = re.compile(r"@[A-Za-z0-9_]{1,32}")


def _safe(value: str) -> str:
    """Защита от формул: ячейки, начинающиеся с = + -, таблицы выполняют как формулу.
    @ тоже опасен, но обычный Telegram-ник (@name) оставляем как есть."""
    value = (value or "").strip()
    if not value:
        return value
    if value[0] in "=+-" or (value[0] == "@" and not TG_HANDLE.fullmatch(value)):
        return "'" + value
    return value


def save_lead(path: str, vk_id: int, name: str, contact: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(FIELDS)
        writer.writerow([datetime.now().isoformat(timespec="seconds"), vk_id, _safe(name), _safe(contact)])
