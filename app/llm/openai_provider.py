"""Cloud explain path: OpenAI API with a request-scoped key.

Mirrors anthropic_provider.py — the key comes from the request body only,
is used for exactly one API call, and is never persisted server-side.
"""
from __future__ import annotations

from openai import OpenAI

from app.config import OPENAI_MODEL
from app.llm.base import build_prompt, parse_response

NAME = "openai"


def explain(chain: dict, api_key: str, model: str = OPENAI_MODEL) -> dict:
    if not api_key:
        raise ValueError("OpenAI provider requires an api_key")

    client = OpenAI(api_key=api_key)
    prompt = build_prompt(chain)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content or ""
    return parse_response(text)
