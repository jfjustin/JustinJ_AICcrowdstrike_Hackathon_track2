"""Private/local explain path: a model already pulled in Ollama (deepseek-r1:8b)."""
from __future__ import annotations

import requests

from app.config import OLLAMA_HOST, OLLAMA_MODEL
from app.llm.base import build_prompt, parse_response

NAME = "ollama"


def is_reachable(host: str = OLLAMA_HOST) -> tuple[bool, list[str]]:
    try:
        resp = requests.get(f"{host}/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return True, models
    except Exception:
        return False, []


def explain(chain: dict, model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> dict:
    prompt = build_prompt(chain)
    resp = requests.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json().get("response", "")
    return parse_response(text)
