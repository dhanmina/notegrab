import json
import os
import threading
import uuid
from datetime import datetime

from . import gist_store

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")
_file_lock   = threading.Lock()


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
    if gist_store.enabled():
        with gist_store.op_lock:
            entries = gist_store.load().get("history", [])
        return [e for e in entries if e.get("user_id") == user_id]
    return [e for e in _load_all() if e.get("user_id") == user_id]


def append(filename: str, size: int, user_id: str, url: str = "", source: str = "") -> dict:
    entry = {
        "id":            str(uuid.uuid4()),
        "user_id":       user_id,
        "filename":      filename,
        "size":          size,
        "url":           url,
        "source":        source,
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    if gist_store.enabled():
        with gist_store.op_lock:
            data    = gist_store.load()
            history = [entry] + list(data.get("history", []))
            gist_store.save({**data, "history": history})
        return entry
    with _file_lock:
        entries = _load_all()
        entries.insert(0, entry)
        _save(entries)
    return entry


def delete(entry_id: str, user_id: str) -> None:
    if gist_store.enabled():
        with gist_store.op_lock:
            data    = gist_store.load()
            history = [e for e in data.get("history", [])
                       if not (e["id"] == entry_id and e.get("user_id") == user_id)]
            gist_store.save({**data, "history": history})
        return
    with _file_lock:
        _save([e for e in _load_all()
               if not (e["id"] == entry_id and e.get("user_id") == user_id)])


def clear(user_id: str) -> None:
    if gist_store.enabled():
        with gist_store.op_lock:
            data    = gist_store.load()
            history = [e for e in data.get("history", []) if e.get("user_id") != user_id]
            gist_store.save({**data, "history": history})
        return
    with _file_lock:
        _save([e for e in _load_all() if e.get("user_id") != user_id])
