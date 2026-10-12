"""Load the data pack once per process and serve it from memory.

chains.jsonl (1,395 rows) and alerts_representatives.jsonl (21,251 rows) are
small enough to live entirely in pandas DataFrames for the life of the Flask
process — no database needed at this scale.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache

import pandas as pd

from app.config import ALERTS_PATH, CHAINS_PATH, EVALUATION_PATH, LABELS_PATH


def _read_jsonl(path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@lru_cache(maxsize=1)
def load_chains_df() -> pd.DataFrame:
    rows = _read_jsonl(CHAINS_PATH)
    df = pd.DataFrame(rows)
    df = df.set_index("chain_id", drop=False)
    return df


@lru_cache(maxsize=1)
def load_alerts_df() -> pd.DataFrame:
    rows = _read_jsonl(ALERTS_PATH)
    df = pd.DataFrame(rows)
    df = df.set_index("alert_id", drop=False)
    return df


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
