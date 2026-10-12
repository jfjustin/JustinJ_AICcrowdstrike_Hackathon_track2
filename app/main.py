"""Flask app: the incident queue API + static shell for Mini Charlotte AI."""
from __future__ import annotations

import math

from flask import Flask, jsonify, render_template, request

from app import feedback
from app.config import BASE_DIR, HOST, PORT
from app.data import get_chain, load_chains_df
from app.llm import anthropic_provider, base as llm_base, cache as llm_cache, ollama_provider
from app.metrics import compute_metrics

GROUND_TRUTH_FIELDS = {"likely_true_positive"}


def _clean_nan(obj):
    """Recursively replace float('nan') with None so jsonify produces valid JSON."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


def _chain_to_payload(row: dict, *, eval_mode: bool, suppressed: bool = False, signature: str | None = None) -> dict:
    payload = dict(row)
    payload.pop("signature", None)
    if not eval_mode:
        for field in GROUND_TRUTH_FIELDS:
            payload.pop(field, None)
    payload["suppressed"] = suppressed
    if suppressed and signature:
        sigs = feedback.suppressed_signatures()
        payload["suppression_reason"] = sigs.get(signature, {}).get("reason")
    verdict = feedback.verdict_for(row["chain_id"])
    payload["analyst_verdict"] = verdict["verdict"] if verdict else None
    return _clean_nan(payload)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/chains")
    def list_chains():
        scenario = request.args.get("scenario")
        min_score = request.args.get("min_score", type=float)
        show_suppressed = request.args.get("show_suppressed", "false").lower() == "true"
        eval_mode = request.args.get("eval", "0") == "1"

        df = load_chains_df()
        if scenario:
            df = df[df["scenario"] == scenario]
        if min_score is not None:
            df = df[df["chain_score"] >= min_score]

        visible_df, suppressed_df = feedback.split_suppressed(df)
        visible_df = visible_df.sort_values("chain_score", ascending=False)
        suppressed_df = suppressed_df.sort_values("chain_score", ascending=False)

        chains = [_chain_to_payload(row.to_dict(), eval_mode=eval_mode) for _, row in visible_df.iterrows()]
        if show_suppressed:
            chains += [
                _chain_to_payload(row.to_dict(), eval_mode=eval_mode, suppressed=True, signature=row["signature"])
                for _, row in suppressed_df.iterrows()
            ]

        return jsonify(
            {
                "chains": chains,
                "total_visible": len(visible_df),
                "total_suppressed": len(suppressed_df),
                "scenarios": sorted(load_chains_df()["scenario"].unique().tolist()),
            }
        )

    @app.get("/api/chains/<chain_id>")
    def chain_detail(chain_id: str):
        eval_mode = request.args.get("eval", "0") == "1"
        chain = get_chain(chain_id)
        if chain is None:
            return jsonify({"error": f"unknown chain_id {chain_id!r}"}), 404

        sig = feedback.is_suppressed(chain)
        payload = _chain_to_payload(chain, eval_mode=eval_mode, suppressed=bool(sig), signature=sig)
        payload["cached_explanations"] = {
            provider: llm_cache.get(chain_id, provider)
            for provider in ("ollama", "anthropic")
            if llm_cache.get(chain_id, provider)
        }
        return jsonify(payload)

    @app.post("/api/chains/<chain_id>/explain")
    def explain_chain(chain_id: str):
        chain = get_chain(chain_id)
        if chain is None:
            return jsonify({"error": f"unknown chain_id {chain_id!r}"}), 404

        body = request.get_json(silent=True) or {}
        provider = body.get("provider", "ollama")
        force = bool(body.get("force"))

        if not force:
            cached = llm_cache.get(chain_id, provider)
            if cached:
                return jsonify(cached)

        used_provider = provider
        try:
            if provider == "ollama":
                result = ollama_provider.explain(chain)
            elif provider == "anthropic":
                api_key = body.get("api_key", "")
                result = anthropic_provider.explain(chain, api_key=api_key)
            else:
                return jsonify({"error": f"unknown provider {provider!r}"}), 400
        except Exception as exc:
            result = llm_base.fallback_explanation(chain)
            result["provider_error"] = str(exc)
            used_provider = "fallback"

        llm_cache.set(chain_id, used_provider, result)
        result = {**result, "provider": used_provider}
        return jsonify(result)

    @app.post("/api/chains/<chain_id>/verdict")
    def set_verdict(chain_id: str):
        body = request.get_json(silent=True) or {}
        verdict = body.get("verdict")
        note = body.get("note", "")
        if not verdict:
            return jsonify({"error": "verdict is required"}), 400
        try:
            feedback.record_verdict(chain_id, verdict, note)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True})

    @app.post("/api/chains/<chain_id>/unsuppress")
    def unsuppress_chain(chain_id: str):
        chain = get_chain(chain_id)
        if chain is None:
            return jsonify({"error": f"unknown chain_id {chain_id!r}"}), 404
        sig = feedback.is_suppressed(chain)
        if sig:
            feedback.unsuppress(sig)
        return jsonify({"ok": True})

    @app.get("/api/metrics")
    def metrics():
        k = request.args.get("k", default=20, type=int)
        return jsonify(_clean_nan(compute_metrics(k=k)))

    @app.get("/api/ollama/status")
    def ollama_status():
        reachable, models = ollama_provider.is_reachable()
        return jsonify({"reachable": reachable, "models": models})

    return app


def main():
    app = create_app()
    app.run(host=HOST, port=PORT, debug=True)


if __name__ == "__main__":
    main()
