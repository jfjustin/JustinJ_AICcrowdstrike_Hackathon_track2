"""Live ingestion: POST new alerts -> they run the real detection pipeline
(normalize -> severity score -> dedup -> correlate into chains) in-process,
and the resulting incidents appear in the queue immediately.

POST /api/ingest
{
  "scenario": "live",        # optional batch label (default "live")
  "alerts": [ ... ]          # raw AMiner objects OR simplified dicts
}

Simplified alert shape (only ts + host are required):
  {"ts": 1720000000.0 | "2026-10-12T14:00:00Z",
   "host": "10.9.8.7",
   "detector": "EntropyDetector",
   "detector_name": "High entropy in DNS domain",
   "log_source": "/var/log/dnsmasq.log",
   "message": "query[A] aB3dE9xQ2....",
   "training_mode": false}

Raw AMiner shape:
  {"AnalysisComponent": {...}, "LogData": {...}, "AMiner": {"ID": "host"}}

Scoring/dedup/correlation parameters mirror data/process_ait_ads.py.reference.
New chain ids continue the existing sequence (chain-1396, ...). Ingested
alerts that land within 30 min of an existing chain on the same host extend
that chain instead of starting a new one. Everything persists under
runtime/live_*.jsonl (gitignored); static data/ files are never touched.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from app import data as data_mod
from app.config import LIVE_ALERTS_PATH, LIVE_CHAINS_PATH

_lock = threading.Lock()

BASE_SEV = {
    "EntropyDetector": 90,
    "EventCountClusterDetector": 70,
    "EventFrequencyDetector": 70,
    "NewMatchPathValueComboDetector": 50,
    "NewMatchPathDetector": 40,
    "ValueRangeDetector": 35,
    "MatchValueAverageChangeDetector": 35,
    "NewMatchPathValueDetector": 30,
    "CharsetDetector": 25,
}
WIN = 900    # dedup window (s): same signature collapses
GAP = 1800   # correlation gap (s): chain split threshold
MAX_BATCH = 5000
ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(ISO_FMT)


def _parse_ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def _dampeners(det, source, raw, values, training):
    mult, why = 1.0, []
    if training:
        mult *= 0.5
        why.append("training_mode")
    if "system.cpu.log" in source:
        mult *= 0.4
        why.append("infra_metric_noise")
    if "audit" in source and "/usr/sbin/cron" in raw:
        mult *= 0.4
        why.append("cron_noise")
    if det == "NewMatchPathValueDetector" and "intranet-access.log" in source:
        v = "".join(values or [])
        if v and all(c.isdigit() or c in ".' " for c in v) and len(v) < 24:
            mult *= 0.5
            why.append("benign_web_value")
    return mult, why


def _sig(det, host, source, values, raw) -> str:
    key = "|".join([det, host, source, str(values)[:60] if values else raw[:60]])
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _clean_name(n) -> str:
    return (n or "").replace("AMiner: ", "").rstrip(".")


def _normalize_one(item: dict, scenario: str, idx: int, labels: dict) -> dict:
    """Accept raw AMiner JSON or the simplified shape -> flat alert record."""
    if isinstance(item.get("AnalysisComponent"), dict) and isinstance(item.get("LogData"), dict):
        ac, ld = item["AnalysisComponent"], item["LogData"]
        det = ac.get("AnalysisComponentType", "unknown")
        det_name = _clean_name(ac.get("AnalysisComponentName"))
        ts = float(ld.get("DetectionTimestamp", ld.get("Timestamps", [time.time()]))[0])
        host = item.get("AMiner", {}).get("ID", "unknown")
        source = (ld.get("LogResources") or ["unknown"])[0]
        raw = (ld.get("RawLogData") or [""])[0][:200]
        values = ac.get("AffectedLogAtomValues")
        training = bool(ac.get("TrainingMode"))
        message = f"{det_name} on {host} [{source.split('/')[-1]}]: {raw[:120]}"
    else:
        det = item.get("detector", "NewMatchPathDetector")
        det_name = item.get("detector_name") or _clean_name(det)
        if "ts" not in item:
            raise ValueError(f"alert {idx}: simplified shape needs 'ts'")
        ts = _parse_ts(item["ts"])
        host = item.get("host") or "unknown"
        if not item.get("host"):
            raise ValueError(f"alert {idx}: simplified shape needs 'host'")
        source = item.get("log_source", "ingest")
        raw = item.get("message", "")[:200]
        values = item.get("values")
        training = bool(item.get("training_mode"))
        message = item.get("message") or f"{det_name} on {host} [{source}]"
        scenario = item.get("scenario", scenario)

    mult, why = _dampeners(det, source, raw, values, training)
    steps = [s for s, a, b in labels.get(scenario, []) if a <= ts <= b]
    return {
        "scenario": scenario,
        "ts": ts,
        "ts_iso": _iso(ts),
        "host": host,
        "log_source": source,
        "detector": det,
        "detector_name": det_name,
        "severity": round(BASE_SEV.get(det, 20) * mult, 1),
        "message": message[:220],
        "training_mode": training,
        "dampened": why,
        "sig": _sig(det, host, source, values, raw),
        "dup_of": None,
        "dup_count": 1,
        "in_attack_window": bool(steps),
        "attack_steps": steps,
        "rank": None,
        "chain_id": None,
    }


def _chain_bounds(chain: dict) -> tuple[float, float]:
    s = datetime.strptime(chain["start_iso"], ISO_FMT).replace(tzinfo=timezone.utc).timestamp()
    e = datetime.strptime(chain["end_iso"], ISO_FMT).replace(tzinfo=timezone.utc).timestamp()
    return s, e


def _fmt_context(rep: dict) -> dict:
    return {"ts_iso": rep["ts_iso"], "severity": rep["severity"],
            "detector": rep["detector"], "message": rep["message"]}


def _refresh_chain(chain: dict, new_reps: list[dict]) -> dict:
    """Fold newly attached representatives into an existing chain row."""
    members_ts = [_parse_ts_iso(chain["start_iso"]), _parse_ts_iso(chain["end_iso"])]
    members_ts += [r["ts"] for r in new_reps]
    dets = dict(chain.get("detectors") or {})
    for r in new_reps:
        dets[r["detector"]] = dets.get(r["detector"], 0) + 1
    steps = sorted(set(chain.get("attack_steps_covered") or []) |
                   {s for r in new_reps for s in r["attack_steps"]})
    ctx = sorted((chain.get("context_alerts") or []) + [_fmt_context(r) for r in new_reps],
                 key=lambda c: -c["severity"])[:8]
    max_sev = max([chain.get("max_severity", 0)] + [r["severity"] for r in new_reps])
    n = chain["alert_count"] + len(new_reps)
    chain.update({
        "start_iso": _iso(min(members_ts)),
        "end_iso": _iso(max(members_ts)),
        "alert_count": n,
        "max_severity": max_sev,
        "chain_score": round(max_sev * (1 + 0.5 * math.log10(n)), 1),
        "detectors": dets,
        "attack_steps_covered": steps,
        "likely_true_positive": bool(steps),
        "context_alerts": ctx,
        "member_ids": list(chain.get("member_ids") or []) + [r["alert_id"] for r in new_reps],
    })
    return chain


def _parse_ts_iso(s: str) -> float:
    return datetime.strptime(s, ISO_FMT).replace(tzinfo=timezone.utc).timestamp()


def _next_chain_id(existing_ids) -> int:
    nums = [int(m.group(1)) for cid in existing_ids
            for m in [re.search(r"chain-(\d+)$", cid)] if m]
    return (max(nums) if nums else 0) + 1


def _append_jsonl(path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def ingest_batch(alerts: list[dict], scenario: str = "live") -> dict:
    """Run the detection pipeline on a posted batch. Returns a summary dict."""
    if not isinstance(alerts, list) or not alerts:
        raise ValueError("'alerts' must be a non-empty list")
    if len(alerts) > MAX_BATCH:
        raise ValueError(f"batch too large (max {MAX_BATCH})")

    with _lock:
        labels = data_mod.load_labels()
        errors, normalized = [], []
        for i, item in enumerate(alerts):
            try:
                normalized.append(_normalize_one(item, scenario, i, labels))
            except Exception as exc:  # per-item failure must not kill the batch
                errors.append(f"alert {i}: {exc}")
        if not normalized:
            raise ValueError("no valid alerts: " + "; ".join(errors[:5]))

        # --- dedup: same (scenario, host, sig) within WIN collapses ---
        # alert_ids are assigned before dedup so duplicates can reference them
        stamp = int(time.time() * 1000)
        for i, a in enumerate(normalized):
            a["alert_id"] = f"live:{stamp}:{i}"
        normalized.sort(key=lambda a: (a["scenario"], a["host"], a["sig"], a["ts"]))
        reps, last = [], {}
        for a in normalized:
            k = (a["scenario"], a["host"], a["sig"])
            prev = last.get(k)
            if prev and a["ts"] - prev["ts"] <= WIN:
                a["dup_of"] = prev["alert_id"]
                prev["dup_count"] += 1
            else:
                last[k] = a
                reps.append(a)

        # --- correlate: attach to existing chains, else gap-split new ones ---
        df = data_mod.load_chains_df()
        chains = [row.to_dict() for _, row in df.iterrows()]
        bounds = {c["chain_id"]: _chain_bounds(c) for c in chains}
        attached: dict[str, list[dict]] = defaultdict(list)
        orphans: list[dict] = []
        for r in sorted(reps, key=lambda a: a["ts"]):
            best, best_end = None, -1.0
            for c in chains:
                if c["host"] != r["host"]:
                    continue
                s, e = bounds[c["chain_id"]]
                if s - GAP <= r["ts"] <= e + GAP and e > best_end:
                    best, best_end = c, e
            if best is None:
                orphans.append(r)
            else:
                attached[best["chain_id"]].append(r)

        touched_ids: set[str] = set()
        for cid, new_reps in attached.items():
            chain = next(c for c in chains if c["chain_id"] == cid)
            _refresh_chain(chain, new_reps)
            for r in new_reps:
                r["chain_id"] = cid
            touched_ids.add(cid)

        # --- new chains from orphans: per (scenario, host), split on GAP ---
        new_chain_rows = []
        nxt = _next_chain_id([c["chain_id"] for c in chains])
        grp: dict[tuple, list[dict]] = defaultdict(list)
        for r in orphans:
            grp[(r["scenario"], r["host"])].append(r)
        for (sc, host), lst in sorted(grp.items()):
            lst.sort(key=lambda a: a["ts"])
            cur = [lst[0]]
            bundles = []
            for a in lst[1:]:
                if a["ts"] - cur[-1]["ts"] > GAP:
                    bundles.append(cur)
                    cur = [a]
                else:
                    cur.append(a)
            bundles.append(cur)
            for members in bundles:
                cid = f"chain-{nxt:04d}"
                nxt += 1
                members.sort(key=lambda a: (-a["severity"], a["ts"]))
                dets: dict[str, int] = defaultdict(int)
                for m in members:
                    dets[m["detector"]] += 1
                steps = sorted({s for m in members for s in m["attack_steps"]})
                max_sev = max(m["severity"] for m in members)
                n = len(members)
                row = {
                    "chain_id": cid,
                    "scenario": sc,
                    "host": host,
                    "start_iso": _iso(min(m["ts"] for m in members)),
                    "end_iso": _iso(max(m["ts"] for m in members)),
                    "alert_count": n,
                    "max_severity": max_sev,
                    "chain_score": round(max_sev * (1 + 0.5 * math.log10(n)), 1),
                    "detectors": dict(dets),
                    "attack_steps_covered": steps,
                    "likely_true_positive": bool(steps),
                    "context_alerts": [_fmt_context(m) for m in members[:8]],
                    "member_ids": [m["alert_id"] for m in members],
                }
                for m in members:
                    m["chain_id"] = cid
                new_chain_rows.append(row)
                touched_ids.add(cid)

        # --- persist live layer + refresh caches ---
        updated_rows = [c for c in chains if c["chain_id"] in attached]
        _append_jsonl(LIVE_CHAINS_PATH, updated_rows + new_chain_rows)
        _append_jsonl(LIVE_ALERTS_PATH, [{k: r[k] for k in
            ("alert_id", "scenario", "ts", "ts_iso", "host", "log_source", "detector",
             "detector_name", "severity", "message", "training_mode", "dampened",
             "dup_count", "in_attack_window", "attack_steps", "rank", "chain_id")}
            for r in reps])
        data_mod.refresh_data()

        return {
            "received": len(alerts),
            "normalized": len(normalized),
            "representatives": len(reps),
            "duplicates_collapsed": len(normalized) - len(reps),
            "new_chains": [r["chain_id"] for r in new_chain_rows],
            "attached": {cid: len(v) for cid, v in attached.items()},
            "touched_chain_ids": sorted(touched_ids),
            "errors": errors,
        }
