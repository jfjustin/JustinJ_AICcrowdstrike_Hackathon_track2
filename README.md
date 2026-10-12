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
ollama pull deepseek-r1:8b   # local default; skip if already pulled
ollama pull gpt-oss:20b       # optional second local/free model (~13GB)

python -m app.main
# open http://127.0.0.1:8713
```

No API key or `.env` is required to run the full demo — the Ollama path works fully offline,
and if Ollama isn't running either, the app falls back to a deterministic, label-free
explanation template so the UI never shows an error state.

To use a cloud explain path: in the incident detail panel, switch the provider dropdown to
"Cloud — Anthropic API", "Cloud — OpenAI API", or "Cloud — Kimi K3 (Moonshot)" and paste the
matching key into the box that appears. Each key is kept in that browser tab's
`sessionStorage` only (one slot per provider), sent once per explain request, and never written
to disk, logs, or the server's environment.

## Live ingest

`POST /api/ingest` runs the real detection pipeline in-process — normalize →
severity score → 15-min dedup → correlate — on whatever you post. New incidents
appear in the queue immediately; alerts landing within 30 min of an existing
chain on the same host extend that chain instead of starting a new one.

```bash
python -m app.main        # terminal 1
python demo_ingest.py     # terminal 2 — fires a synthetic attack burst
```

Accepts raw AMiner JSON objects or simplified
`{"ts", "host", "detector", "detector_name", "log_source", "message"}` dicts.
Ingested rows persist under `runtime/live_*.jsonl` (gitignored) and are merged
over the static pack on every load — `data/` is never mutated. The analyst
feedback loop applies to live incidents automatically: mark one false positive
and its detector-mix signature suppresses lookalikes.

**Gating it**: set `INGEST_API_KEY` and every `POST /api/ingest` must include
a matching `X-Ingest-Key` header, or it's rejected with 401. Empty (the
local default) means the endpoint is open, which is fine on localhost but
not once this is reachable publicly:

```bash
# local, gate on
INGEST_API_KEY=some-long-random-string python -m app.main

# client side
curl -X POST http://127.0.0.1:8713/api/ingest \
  -H "Content-Type: application/json" \
  -H "X-Ingest-Key: some-long-random-string" \
  -d '{"scenario":"live","alerts":[{"ts":1730000000,"host":"10.1.2.3","detector":"EntropyDetector","message":"..."}]}'

# or with demo_ingest.py
INGEST_API_KEY=some-long-random-string python demo_ingest.py
```

`deploy/azure_deploy.sh` picks up `INGEST_API_KEY` from your shell if set and
pushes it to the App Service as a setting automatically:

```bash
INGEST_API_KEY=some-long-random-string APP_NAME=mini-charlotte-ai-jjiang8 ./deploy/azure_deploy.sh
```

If you deployed already without it, set it after the fact and restart:

```bash
az webapp config appsettings set --name mini-charlotte-ai-jjiang8 \
  --resource-group rg-charlotte-ai --settings INGEST_API_KEY=some-long-random-string
az webapp restart --name mini-charlotte-ai-jjiang8 --resource-group rg-charlotte-ai
```

## How it works

1. **Queue** (`/api/chains`) — chains sorted by `chain_score`, ground truth hidden unless "eval
   mode" is checked.
2. **Explain** (`/api/chains/<id>/explain`) — builds a SOC-analyst prompt from the chain's top-8
   `context_alerts`, asks the selected provider (local Ollama `deepseek-r1:8b` or `gpt-oss:20b`,
   or cloud Anthropic / OpenAI / Kimi K3) for a structured JSON verdict: `summary`, `confidence` (high/medium/low + why),
   `false_positive_hypotheses`, `next_steps`, and a `verdict` (TRUE_POSITIVE / FALSE_POSITIVE /
   NEEDS_REVIEW). Responses are cached to `runtime/llm_cache.json` keyed by chain + provider.
3. **Feedback loop** (`/api/chains/<id>/verdict`) — an analyst confirming or marking a chain false
   positive writes to `runtime/feedback_store.json`. Suppression is derived live from each
   chain's *latest* verdict (no separate mutable suppression store): any chain whose most recent
   verdict is false-positive contributes its `host` + detector-mix signature to the suppressed
   set, and any other chain matching that signature is auto-filtered from the main queue
   (visible under "show suppressed", with the reason). Flipping the verdict back, or hitting
   "unsuppress" in the detail panel, clears it immediately — there's nothing else to keep in
   sync. "Reset demo" in the toolbar wipes all verdicts and the explanation cache for a clean
   re-run.
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
    ollama_provider.py local explain (deepseek-r1:8b or gpt-oss:20b via Ollama)
    anthropic_provider.py  cloud explain: Anthropic (request-scoped API key)
    openai_provider.py     cloud explain: OpenAI (request-scoped API key)
    kimi_provider.py       cloud explain: Kimi K3 / Moonshot (request-scoped API key)
    cache.py           disk cache keyed by (chain_id, provider)
templates/index.html   single-page shell (Queue / Metrics / About)
static/css, static/js  vanilla CSS/JS, no frontend framework
data/                  the processed data pack (see table above)
runtime/                gitignored: feedback_store.json, llm_cache.json (created at startup)
```
