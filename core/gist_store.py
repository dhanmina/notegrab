import json
import logging
import os
import threading

import requests

log = logging.getLogger(__name__)

_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
_GIST_ID = os.environ.get("GIST_ID", "")
_FILE    = "data.json"

# op_lock serialises every load-modify-save cycle across all callers so a
# concurrent flashcard write and history write never clobber each other.
op_lock  = threading.Lock()
_cache: dict | None = None


def enabled() -> bool:
    return bool(_TOKEN and _GIST_ID)


def _hdrs() -> dict:
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch() -> dict:
    r = requests.get(
        f"https://api.github.com/gists/{_GIST_ID}",
        headers=_hdrs(), timeout=15,
    )
    r.raise_for_status()
    return json.loads(r.json()["files"][_FILE]["content"])


def _push(data: dict) -> None:
    requests.patch(
        f"https://api.github.com/gists/{_GIST_ID}",
        json={"files": {_FILE: {"content": json.dumps(data, indent=2)}}},
        headers=_hdrs(), timeout=15,
    ).raise_for_status()


def load() -> dict:
    """Return cached data, fetching from Gist on first call. Must be called inside op_lock."""
    global _cache
    if _cache is None:
        try:
            _cache = _fetch()
            log.info("gist: loaded — %d set(s), %d history entries",
                     len(_cache.get("flashcards", [])),
                     len(_cache.get("history", [])))
        except Exception as e:
            log.error("gist: initial load failed: %s", e)
            _cache = {"flashcards": [], "history": []}
    return _cache


def save(data: dict) -> None:
    """Update the in-memory cache and push to Gist. Must be called inside op_lock."""
    global _cache
    _cache = data
    try:
        _push(data)
        log.debug("gist: saved")
    except Exception as e:
        log.error("gist: save failed: %s", e)


def warm() -> None:
    """Pre-load the cache in a background thread so the first real request is fast."""
    with op_lock:
        load()
