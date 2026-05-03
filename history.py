import json
import os
import threading
import uuid
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")
_lock = threading.Lock()


def load() -> list:
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def append(filename: str, size: int) -> dict:
    entry = {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "size": size,
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        entries = load()
        entries.insert(0, entry)
        _save(entries)
    return entry


def delete(entry_id: str):
    with _lock:
        _save([e for e in load() if e["id"] != entry_id])


def clear():
    with _lock:
        _save([])
