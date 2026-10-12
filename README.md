# Mini Charlotte AI — Track 2

A small CrowdStrike-Charlotte-style triage system: it takes a correlated alert queue, ranks
incidents, explains the top ones in plain English with an LLM, and learns from analyst feedback
to suppress repeat false positives — live, against ground truth, not a static slide.

**The demo in one line:** a 3,842-alert intrusion burst on one host (scans → webshell) collapses
into a single ranked incident with an LLM explanation attached. "3,842 alerts → 1 incident."

## Data

Source: AIT Alert Data Set (AMiner IDS alerts, 8 scenarios, each hit by a scan → webshell →
password-cracking → reverse-shell → privesc → DNS-exfil attack). Already processed into:

| file | rows | what |
|---|---|---|
| `data/alerts_representatives.jsonl` | 21,251 | deduped alert queue, ranked per scenario |
| `data/chains.jsonl` | 1,395 | correlated incidents, ranked by `chain_score`, each with top-8 `context_alerts` |
| `data/labels.csv` | 79 | ground-truth attack windows — used only for the Metrics tab |
| `data/evaluation.json` | — | baseline precision/volume numbers this build is meant to beat |

`chain_score = max_severity × (1 + 0.5·log10(n))`, computed label-free, so burst incidents
outrank lone noisy alerts without ever looking at `labels.csv`. See `data/process_ait_ads.py.reference`
for the full original pipeline.

## Run it

```bash
pip install -r requirements.txt

# optional, for the local explain provider:
ollama pull deepseek-r1:8b   # skip if already pulled

python -m app.main
# open http://127.0.0.1:8713
```

No API key or `.env` is required to run the full demo — the Ollama path works fully offline,
and if Ollama isn't running either, the app falls back to a deterministic, label-free
explanation template so the UI never shows an error state.

To use the cloud explain path: in the incident detail panel, switch the provider dropdown to
"Cloud — Anthropic API" and paste a key into the box that appears. The key is kept in that
browser tab's `sessionStorage` only, sent once per explain request, and never written to disk,
logs, or the server's environment.

## How it works

1. **Queue** (`/api/chains`) — chains sorted by `chain_score`, ground truth hidden unless "eval
   mode" is checked.
2. **Explain** (`/api/chains/<id>/explain`) — builds a SOC-analyst prompt from the chain's top-8
   `context_alerts`, asks the selected provider (local Ollama `deepseek-r1:8b` or cloud
   Anthropic) for a structured JSON verdict: `summary`, `confidence` (high/medium/low + why),
   `false_positive_hypotheses`, `next_steps`, and a `verdict` (TRUE_POSITIVE / FALSE_POSITIVE /
   NEEDS_REVIEW). Responses are cached to `runtime/llm_cache.json` keyed by chain + provider.
3. **Feedback loop** (`/api/chains/<id>/verdict`) — an analyst confirming or marking a chain false
   positive writes to `runtime/feedback_store.json`. A false-positive verdict registers a
   suppression signature (`host` + detector mix); any future chain matching it is auto-filtered
   from the main queue (visible under "show suppressed", with the reason and an unsuppress
   action).
4. **Metrics** (`/api/metrics`) — recomputes precision@k and volume reduction live, before vs.
   after the suppressions currently in effect, against `labels.csv` — the actual money slide,
   not a fixed number.

## Honest caveats (carried over from the data pack)

- Per-alert severity ranking alone has weak precision — benign high-entropy DNS queries score 90
  and float to the top just like real exfiltration traffic would. That's the whole reason the
  correlation step and the feedback-loop suppression exist; raw severity was never meant to be
  the final ranking.
- A few exfil-like DNS bursts fall outside the labeled attack windows in `labels.csv` (labels
  don't necessarily cover every repetition of an attack). The LLM explanation and the analyst's
  verdict are the arbiter for those — exactly like a real SOC, where ground truth doesn't exist
  until someone decides it does.

## Project layout

```
app/
  main.py              Flask routes
  config.py            settings (env/.env-driven)
  data.py              loads chains/alerts/labels/evaluation into memory once
  feedback.py          verdict + suppression store
  metrics.py           live precision/volume recomputation
  llm/
    base.py            shared prompt + JSON response parsing + offline fallback
    ollama_provider.py local explain (deepseek-r1:8b via Ollama)
    anthropic_provider.py  cloud explain (request-scoped API key)
    cache.py           disk cache keyed by (chain_id, provider)
templates/index.html   single-page shell (Queue / Metrics / About)
static/css, static/js  vanilla CSS/JS, no frontend framework
data/                  the processed data pack (see table above)
runtime/                gitignored: feedback_store.json, llm_cache.json (created at startup)
```
