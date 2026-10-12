"""Live 'money slide' numbers: volume reduction + precision@k, before vs
after the analyst feedback loop's suppressions — recomputed against
labels.csv on every request, not a static slide.
"""
from __future__ import annotations

from app.data import load_chains_df, load_evaluation
from app.feedback import split_suppressed

DEFAULT_K = 20


def _precision_at_k(df, k: int) -> float | None:
    if df.empty:
        return None
    top_k = df.sort_values("chain_score", ascending=False).head(k)
    if top_k.empty:
        return None
    return round(100 * top_k["likely_true_positive"].mean(), 1)


def compute_metrics(k: int = DEFAULT_K) -> dict:
    evaluation = load_evaluation()
    chains_df = load_chains_df()

    raw_total = sum(s["alerts_raw"] for s in evaluation.values())
    dedup_total = sum(s["alerts_after_dedup"] for s in evaluation.values())
    chain_total_before = len(chains_df)

    visible_df, _ = split_suppressed(chains_df)
    chain_total_after = len(visible_df)

    headline = None
    true_positive_chains = chains_df[chains_df["likely_true_positive"] == True]  # noqa: E712
    if not true_positive_chains.empty:
        top = true_positive_chains.sort_values("alert_count", ascending=False).iloc[0]
        headline = {
            "chain_id": top["chain_id"],
            "scenario": top["scenario"],
            "host": top["host"],
            "alert_count": int(top["alert_count"]),
            "attack_steps_covered": top["attack_steps_covered"],
        }

    return {
        "k": k,
        "volume": {
            "raw_alerts": raw_total,
            "deduped_alerts": dedup_total,
            "chains_before_feedback": chain_total_before,
            "chains_after_feedback": chain_total_after,
            "suppressed_count": chain_total_before - chain_total_after,
        },
        "precision_at_k": {
            "before": _precision_at_k(chains_df, k),
            "after": _precision_at_k(visible_df, k),
        },
        "baseline_by_scenario": evaluation,
        "headline_chain": headline,
    }
