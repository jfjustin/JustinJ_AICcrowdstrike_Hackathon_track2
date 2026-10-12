"""Disk cache for explanations, keyed by (chain_id, provider).

Keeps repeat clicks in a demo free and means the queue still shows prior
explanations even if the model/network is unavailable later.
"""
from __future__ import annotations

import json
import threading
import time

from app.config import LLM_CACHE_PATH

_lock = threading.Lock()


def _load() -> dict:
    if not LLM_CACHE_PATH.exists():
        return {}
    with open(LLM_CACHE_PATH) as f:
        return json.load(f)


def _save(cache: dict) -> None:
    tmp = LLM_CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    tmp.replace(LLM_CACHE_PATH)


def _key(chain_id: str, provider: str) -> str:
    return f"{chain_id}|{provider}"


def get(chain_id: str, provider: str) -> dict | None:
    with _lock:
        cache = _load()
        return cache.get(_key(chain_id, provider))


def set(chain_id: str, provider: str, response: dict) -> None:
    with _lock:
        cache = _load()
        cache[_key(chain_id, provider)] = {**response, "cached_at": time.time(), "provider": provider}
        _save(cache)


def clear() -> None:
    with _lock:
        _save({})
