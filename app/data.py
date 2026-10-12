"""Load the data pack once per process and serve it from memory.

chains.jsonl (1,395 rows) and alerts_representatives.jsonl (21,251 rows) are
small enough to live entirely in pandas DataFrames for the life of the Flask
process — no database needed at this scale.

Live ingestion (/api/ingest) appends to runtime/live_chains.jsonl and
runtime/live_alerts.jsonl (gitignored). Those rows are merged over the static
pack on load: a live row with the same chain_id replaces the static one
(chain extension), new ids are appended. Static data/ files are never mutated.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache

import pandas as pd

from app.config import (
    ALERTS_PATH,
    CHAINS_PATH,
    EVALUATION_PATH,
    LABELS_PATH,
    LIVE_ALERTS_PATH,
    LIVE_CHAINS_PATH,
)


def _read_jsonl(path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_live_rows(path) -> list[dict]:
    """Live rows, last write wins per chain_id/alert_id."""
    if not path.exists():
        return []
    deduped: dict[str, dict] = {}
    for row in _read_jsonl(path):
        key = row.get("chain_id") or row.get("alert_id")
        if key:
            deduped[key] = row
    return list(deduped.values())


def _merge_live(static_rows: list[dict], live_rows: list[dict], key: str) -> list[dict]:
    if not live_rows:
        return static_rows
    live_ids = {r[key] for r in live_rows}
    return [r for r in static_rows if r.get(key) not in live_ids] + live_rows


@lru_cache(maxsize=1)
def load_chains_df() -> pd.DataFrame:
    rows = _merge_live(_read_jsonl(CHAINS_PATH), _read_live_rows(LIVE_CHAINS_PATH), "chain_id")
    df = pd.DataFrame(rows)
    df = df.set_index("chain_id", drop=False)
    return df


@lru_cache(maxsize=1)
def load_alerts_df() -> pd.DataFrame:
    rows = _merge_live(_read_jsonl(ALERTS_PATH), _read_live_rows(LIVE_ALERTS_PATH), "alert_id")
    df = pd.DataFrame(rows)
    df = df.set_index("alert_id", drop=False)
    return df


def refresh_data() -> None:
    """Call after ingestion so the next request sees the merged live layer."""
    load_chains_df.cache_clear()
    load_alerts_df.cache_clear()


@lru_cache(maxsize=1)
def load_labels() -> dict[str, list[tuple[str, float, float]]]:
    """scenario -> [(attack_step, start_epoch, end_epoch), ...]"""
    labels: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    with open(LABELS_PATH) as f:
        for row in csv.DictReader(f):
            labels[row["scenario"]].append(
                (row["attack"], float(row["start"]), float(row["end"]))
            )
    return dict(labels)


@lru_cache(maxsize=1)
def load_evaluation() -> dict:
    with open(EVALUATION_PATH) as f:
        return json.load(f)


def get_chain(chain_id: str) -> dict | None:
    df = load_chains_df()
    if chain_id not in df.index:
        return None
    return df.loc[chain_id].to_dict()


def chain_signature(chain: dict) -> str:
    """Identity used for suppression matching: host + sorted detector set.

    Chains sharing a host and the same mix of detector types are treated as
    "the same kind of noise" once an analyst marks one a false positive.
    """
    detectors = sorted((chain.get("detectors") or {}).keys())
    return f"{chain.get('host')}|{','.join(detectors)}"
