import json
import os
import re
import threading
import uuid
from datetime import datetime

# Store each set as its own JSON file in flashcards/ at the project root
SETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flashcards")
os.makedirs(SETS_DIR, exist_ok=True)
_MARKER = "flashcard_set"
_lock   = threading.Lock()


def _title_to_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s\-]', '', title).strip()
    safe = re.sub(r'\s+', '_', safe)
    safe = safe[:80] or 'untitled'
    return f"{safe}.json"


def _set_path(filename: str) -> str:
    return os.path.join(SETS_DIR, filename)


def _load_file(path: str) -> dict | None:
    try:
        with open(path) as f:
            d = json.load(f)
        if d.get("_type") == _MARKER:
            return d
    except Exception:
        pass
    return None


def _save_file(path: str, entry: dict):
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)


def _all_set_paths() -> list[str]:
    try:
        return [
            os.path.join(SETS_DIR, name)
            for name in os.listdir(SETS_DIR)
            if name.endswith(".json")
        ]
    except OSError:
        return []


def _unique_filename(title: str, exclude_id: str | None = None) -> str:
    base = _title_to_filename(title)
    path = _set_path(base)
    if not os.path.exists(path):
        return base
    existing = _load_file(path)
    if existing and existing.get("id") == exclude_id:
        return base
    stem = base[:-5]
    i = 2
    while True:
        candidate = f"{stem}_{i}.json"
        p = _set_path(candidate)
        if not os.path.exists(p):
            return candidate
        existing = _load_file(p)
        if existing and existing.get("id") == exclude_id:
            return candidate
        i += 1


def load() -> list:
    result = []
    for path in _all_set_paths():
        e = _load_file(path)
        if e:
            result.append(e)
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result


def get_one(set_id: str) -> dict | None:
    for path in _all_set_paths():
        e = _load_file(path)
        if e and e.get("id") == set_id:
            return e
    return None


def create(title: str, url: str, answers: str, questions: list) -> dict:
    now      = datetime.now().isoformat(timespec="seconds")
    filename = _unique_filename(title)
    entry = {
        "_type":      _MARKER,
        "id":         str(uuid.uuid4()),
        "filename":   filename,
        "title":      title,
        "url":        url,
        "answers":    answers,
        "questions":  questions,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        _save_file(_set_path(filename), entry)
    return entry


def update(set_id: str, **kwargs) -> dict | None:
    with _lock:
        for path in _all_set_paths():
            e = _load_file(path)
            if not (e and e.get("id") == set_id):
                continue
            old_title = e.get("title", "")
            new_title = kwargs.get("title", old_title)
            e.update(kwargs)
            e["updated_at"] = datetime.now().isoformat(timespec="seconds")
            if new_title != old_title:
                new_filename = _unique_filename(new_title, exclude_id=set_id)
                new_path     = _set_path(new_filename)
                e["filename"] = new_filename
                _save_file(new_path, e)
                os.remove(path)
            else:
                _save_file(path, e)
            return e
    return None


def upsert(set_data: dict) -> tuple[dict, bool]:
    set_id = set_data.get("id") or str(uuid.uuid4())
    now    = datetime.now().isoformat(timespec="seconds")
    with _lock:
        existing_path  = None
        existing_entry = None
        for path in _all_set_paths():
            e = _load_file(path)
            if e and e.get("id") == set_id:
                existing_path  = path
                existing_entry = e
                break
        title    = set_data.get("title", "untitled")
        filename = _unique_filename(title, exclude_id=set_id)
        new_path = _set_path(filename)
        entry = {
            **set_data,
            "_type":      _MARKER,
            "id":         set_id,
            "filename":   filename,
            "updated_at": now,
            "created_at": existing_entry.get("created_at", now) if existing_entry else now,
        }
        _save_file(new_path, entry)
        if existing_path and existing_path != new_path:
            os.remove(existing_path)
        return entry, existing_path is not None


def delete(set_id: str):
    with _lock:
        for path in _all_set_paths():
            e = _load_file(path)
            if e and e.get("id") == set_id:
                os.remove(path)
                return
