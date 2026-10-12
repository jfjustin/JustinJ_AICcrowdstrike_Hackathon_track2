"""Analyst feedback loop: verdicts on chains + derived suppression rules.

A single JSON file is enough for a single-process demo. Suppression is
derived live from each chain's *latest* verdict, not stored as separate
mutable state — one source of truth, so flipping a verdict back to TP/review
automatically clears the suppression on the next read instead of needing a
separate "unsuppress" write to stay in sync.
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
        return {"verdicts": []}
    with open(FEEDBACK_STORE_PATH) as f:
        store = json.load(f)
    store.setdefault("verdicts", [])
    return store


def _save(store: dict) -> None:
    tmp = FEEDBACK_STORE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2)
    tmp.replace(FEEDBACK_STORE_PATH)


def _latest_entries(store: dict) -> dict[str, dict]:
    """chain_id -> its most recent verdict entry (later entries win)."""
    latest: dict[str, dict] = {}
    for entry in store["verdicts"]:
        latest[entry["chain_id"]] = entry
    return latest


def record_verdict(chain_id: str, verdict: str, note: str = "") -> dict:
    """Accepts 'tp'/'fp'/'review' or 'TRUE_POSITIVE'/'FALSE_POSITIVE'/'NEEDS_REVIEW'."""
    chain = get_chain(chain_id)
    if chain is None:
        raise ValueError(f"unknown chain_id {chain_id!r}")
    normalize_verdict(verdict)  # validate, raises on unknown values

    with _lock:
        store = _load()
        store["verdicts"].append(
            {"chain_id": chain_id, "verdict": verdict, "note": note, "ts": time.time()}
        )
        _save(store)
        return store


def get_store() -> dict:
    with _lock:
        return _load()


def suppressed_signatures() -> dict:
    """signature -> {reason, source_chain_id, ts}, derived live from whichever
    chains currently have a false-positive verdict as their latest entry."""
    store = get_store()
    sigs: dict[str, dict] = {}
    for chain_id, entry in _latest_entries(store).items():
        if normalize_verdict(entry["verdict"]) != "fp":
            continue
        chain = get_chain(chain_id)
        if chain is None:
            continue
        sig = chain_signature(chain)
        sigs[sig] = {
            "reason": f"analyst marked chain {chain_id} as false positive",
            "source_chain_id": chain_id,
            "ts": entry["ts"],
        }
    return sigs


def verdict_for(chain_id: str) -> dict | None:
    store = get_store()
    return _latest_entries(store).get(chain_id)


def is_suppressed(chain: dict, signatures: dict | None = None) -> str | None:
    """Returns the matching suppression signature, or None."""
    sigs = signatures if signatures is not None else suppressed_signatures()
    sig = chain_signature(chain)
    return sig if sig in sigs else None


def unsuppress(signature: str) -> dict:
    """Clears a suppression by overriding every chain currently driving it
    (latest verdict FP, matching signature) with a 'review' verdict."""
    with _lock:
        store = _load()
        for chain_id, entry in _latest_entries(store).items():
            if normalize_verdict(entry["verdict"]) != "fp":
                continue
            chain = get_chain(chain_id)
            if chain is None or chain_signature(chain) != signature:
                continue
            store["verdicts"].append(
                {
                    "chain_id": chain_id,
                    "verdict": "review",
                    "note": "auto-cleared via unsuppress",
                    "ts": time.time(),
                }
            )
        _save(store)
        return store


def reset_all() -> None:
    with _lock:
        _save({"verdicts": []})


def split_suppressed(df):
    """Returns (visible_df, suppressed_df) with a 'signature' column added."""
    sigs = suppressed_signatures()
    signature_col = df.apply(lambda row: chain_signature(row.to_dict()), axis=1)
    df = df.assign(signature=signature_col)
    is_sup = df["signature"].isin(sigs.keys())
    return df[~is_sup], df[is_sup]
