import json
import os
import threading
import uuid
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")
_lock = threading.Lock()


def _load_all() -> list:
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def load(user_id: str) -> list:
    return [e for e in _load_all() if e.get("user_id") == user_id]


def append(filename: str, size: int, user_id: str) -> dict:
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "filename": filename,
        "size": size,
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        entries = _load_all()
        entries.insert(0, entry)
        _save(entries)
    return entry


def delete(entry_id: str, user_id: str):
    with _lock:
        _save([e for e in _load_all()
               if not (e["id"] == entry_id and e.get("user_id") == user_id)])


def clear(user_id: str):
    with _lock:
        _save([e for e in _load_all() if e.get("user_id") != user_id])
