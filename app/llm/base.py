"""Shared SOC-analyst prompt + response parsing for every LLM provider.

Both providers (local Ollama, cloud Anthropic) are asked for the exact same
JSON shape, so the frontend never has to know which one answered.
"""
from __future__ import annotations

import json
import re

RESPONSE_SHAPE = """{
  "summary": "2-3 sentences: what most likely happened, no jargon",
  "confidence": "high | medium | low",
  "confidence_why": "one line",
  "false_positive_hypotheses": ["benign explanation 1", "benign explanation 2"],
  "next_steps": ["concrete step 1", "concrete step 2", "concrete step 3"],
  "verdict": "TRUE_POSITIVE | FALSE_POSITIVE | NEEDS_REVIEW"
}"""

VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_VERDICT = {"TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"}


def build_prompt(chain: dict) -> str:
    alerts = chain.get("context_alerts") or []
    alert_lines = [
        f"- [{a.get('ts_iso')}] (sev {a.get('severity')}) {a.get('detector')}: {a.get('message')}"
        for a in alerts
    ]
    detectors = chain.get("detectors") or {}
    detector_summary = ", ".join(f"{k} x{v}" for k, v in detectors.items())

    return f"""You are a senior SOC analyst. Explain this correlated alert incident in plain English.

Incident {chain.get('chain_id')} on host {chain.get('host')} ({chain.get('scenario')}), {chain.get('start_iso')} to {chain.get('end_iso')}.
{chain.get('alert_count')} alerts, max severity {chain.get('max_severity')}. Detectors involved: {detector_summary}.

Top alerts:
{chr(10).join(alert_lines)}

Respond in this exact JSON shape:
{RESPONSE_SHAPE}"""


def _strip_thinking(text: str) -> str:
    """Local reasoning models (e.g. deepseek-r1) wrap scratch work in <think> tags."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def parse_response(raw_text: str) -> dict:
    text = _strip_thinking(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object found in model response: {raw_text[:300]!r}")
        data = json.loads(match.group(0))

    required = {
        "summary",
        "confidence",
        "confidence_why",
        "false_positive_hypotheses",
        "next_steps",
        "verdict",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"model response missing fields {missing}: {data!r}")

    confidence = str(data["confidence"]).strip().lower()
    data["confidence"] = confidence if confidence in VALID_CONFIDENCE else "medium"

    verdict = str(data["verdict"]).strip().upper()
    data["verdict"] = verdict if verdict in VALID_VERDICT else "NEEDS_REVIEW"

    data["false_positive_hypotheses"] = list(data["false_positive_hypotheses"])[:2]
    data["next_steps"] = list(data["next_steps"])[:3]
    return data


def fallback_explanation(chain: dict) -> dict:
    """Deterministic, label-free explanation used when no provider is reachable.

    Built only from chain_score/attack_steps_covered/detectors — the same
    label-free signals the data pack's own scoring uses — never from the
    ground-truth likely_true_positive field, so the fallback can't cheat.
    """
    steps = chain.get("attack_steps_covered") or []
    detectors = list((chain.get("detectors") or {}).keys())
    alert_count = chain.get("alert_count", 0)
    score = chain.get("chain_score", 0)

    if len(steps) >= 3:
        narrative = f"a multi-stage intrusion ({' -> '.join(steps)}) rather than isolated noise"
        verdict = "TRUE_POSITIVE" if score > 50 else "NEEDS_REVIEW"
        confidence = "high" if score > 80 else "medium"
    elif steps:
        narrative = f"an isolated '{steps[0]}'-style event"
        verdict = "NEEDS_REVIEW"
        confidence = "low"
    else:
        narrative = "detector noise with no known attack-step signature"
        verdict = "FALSE_POSITIVE" if alert_count > 500 else "NEEDS_REVIEW"
        confidence = "low"

    return {
        "summary": (
            f"[offline fallback — no LLM reachable] {alert_count} alerts on "
            f"{chain.get('host')} correlated across {', '.join(detectors) or 'one detector'}. "
            f"Pattern looks like {narrative}."
        ),
        "confidence": confidence,
        "confidence_why": "deterministic heuristic from chain_score and attack-step coverage, no model available",
        "false_positive_hypotheses": [
            "Automated scanner, health-check, or monitoring job producing a high-frequency burst",
            "Benign high-entropy string (asset hash, token, or long URL) misclassified by the entropy detector",
        ],
        "next_steps": [
            "Confirm whether the host normally runs a scanner/monitoring agent at this time window",
            "Spot-check 2-3 raw log lines behind the top-severity alerts for obvious benign content",
            "If still ambiguous, route to an analyst for manual review before suppressing",
        ],
        "verdict": verdict,
    }
