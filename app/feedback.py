"""Analyst feedback loop: verdicts on chains + derived suppression rules.

A single JSON file is enough for a single-process demo. A false-positive
verdict registers a suppression signature (host + detector mix) so future
chains matching it are filtered out of the main queue automatically — the
"feedback loop" the data pack's README asks for.
"""
from __future__ import annotations

import json
import threading
import time

from app.config import FEEDBACK_STORE_PATH
from app.data import chain_signature, get_chain

_lock = threading.Lock()

# Accept either the UI's short verdict codes or the LLM's TRUE_POSITIVE /
# FALSE_POSITIVE / NEEDS_REVIEW vocabulary — normalized to one canonical form
# for the suppression check, original string kept for display.
_VERDICT_ALIASES = {
    "tp": "tp",
    "true_positive": "tp",
    "fp": "fp",
    "false_positive": "fp",
    "review": "review",
    "needs_review": "review",
}


def normalize_verdict(verdict: str) -> str:
    key = verdict.strip().lower()
    if key not in _VERDICT_ALIASES:
        raise ValueError(f"unknown verdict {verdict!r}")
    return _VERDICT_ALIASES[key]


def _load() -> dict:
    if not FEEDBACK_STORE_PATH.exists():
        return {"verdicts": [], "suppressed_signatures": {}}
    with open(FEEDBACK_STORE_PATH) as f:
        return json.load(f)


def _save(store: dict) -> None:
    tmp = FEEDBACK_STORE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2)
    tmp.replace(FEEDBACK_STORE_PATH)


def record_verdict(chain_id: str, verdict: str, note: str = "") -> dict:
    """Accepts 'tp'/'fp'/'review' or 'TRUE_POSITIVE'/'FALSE_POSITIVE'/'NEEDS_REVIEW'."""
    chain = get_chain(chain_id)
    if chain is None:
        raise ValueError(f"unknown chain_id {chain_id!r}")
    canonical = normalize_verdict(verdict)

    with _lock:
        store = _load()
        store["verdicts"].append(
            {
                "chain_id": chain_id,
                "verdict": verdict,
                "note": note,
                "ts": time.time(),
            }
        )
        if canonical == "fp":
            sig = chain_signature(chain)
            store["suppressed_signatures"][sig] = {
                "reason": f"analyst marked chain {chain_id} as false positive",
                "source_chain_id": chain_id,
                "ts": time.time(),
            }
        _save(store)
        return store


def unsuppress(signature: str) -> dict:
    with _lock:
        store = _load()
        store["suppressed_signatures"].pop(signature, None)
        _save(store)
        return store


def get_store() -> dict:
    with _lock:
        return _load()


def suppressed_signatures() -> dict:
    return get_store()["suppressed_signatures"]


def verdict_for(chain_id: str) -> dict | None:
    store = get_store()
    for v in reversed(store["verdicts"]):
        if v["chain_id"] == chain_id:
            return v
    return None


def is_suppressed(chain: dict, signatures: dict | None = None) -> str | None:
    """Returns the matching suppression signature, or None."""
    sigs = signatures if signatures is not None else suppressed_signatures()
    sig = chain_signature(chain)
    return sig if sig in sigs else None


def split_suppressed(df):
    """Returns (visible_df, suppressed_df) with a 'signature' column added."""
    sigs = suppressed_signatures()
    signature_col = df.apply(lambda row: chain_signature(row.to_dict()), axis=1)
    df = df.assign(signature=signature_col)
    is_sup = df["signature"].isin(sigs.keys())
    return df[~is_sup], df[is_sup]
