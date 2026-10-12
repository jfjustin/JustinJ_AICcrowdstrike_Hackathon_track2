"""Cloud explain path: Anthropic API with a request-scoped key.

The key is never read from server-side env/disk and never written to disk —
it comes in on the request body from the browser's chatbox-style input and
is used for exactly one API call.
"""
from __future__ import annotations

import anthropic

from app.config import ANTHROPIC_MODEL
from app.llm.base import build_prompt, parse_response

NAME = "anthropic"


def explain(chain: dict, api_key: str, model: str = ANTHROPIC_MODEL) -> dict:
    if not api_key:
        raise ValueError("Anthropic provider requires an api_key")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(chain)
    message = client.messages.create(
        model=model,
        max_tokens=600,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    return parse_response(text)
