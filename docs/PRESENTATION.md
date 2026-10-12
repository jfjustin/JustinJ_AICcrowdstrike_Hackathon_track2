# Presenting solo — approach, script, Q&A prep

## The solo-team reality check

You're the engineer, the presenter, and the demo operator at the same time. Plan around that,
don't fight it:

- **Pre-warm everything before you walk up.** The Ollama explain calls take 45-85s cold. The
  headline chains (harrison's chain-0387, fox's chain-0055) are already cached in
  `runtime/llm_cache.json` from this build session — if you reset the demo or move to a fresh
  machine, re-run `python demo_ingest.py` isn't it; just click "Explain" on those two chains once
  *before* judges arrive. Never let a live LLM call be the thing your 3 minutes is waiting on.
- **Narrate while you click, don't click then narrate.** You have no one to fill silence while a
  page loads. Talk through what's about to happen as you navigate, so dead air reads as pacing,
  not a stall.
- **Know your worst numbers better than anyone in the room.** Judges probe weaknesses, not
  strengths. If you can recite exactly *why* russellmitchell's precision craters from 85.75% raw
  to 28.91% after dedup without flinching, that one answer does more for credibility than any
  slide. (Real answer below, in Q&A.)
- **Decide your fallback path now, not live.** If Wi-Fi is bad: Ollama (local) still works with
  zero network. If Ollama is slow/unavailable: the deterministic fallback template still returns
  a clean, non-error response — the demo literally cannot show a stack trace, show that off if
  asked "what happens when the model's down."
- **One browser tab, two windows max.** The live app + this doc (or the artifact brief) on a
  second screen/phone for your own glancing, not shown to judges.

## Presentation flow (aim for ~3 minutes, leaves room for Q&A)

**0:00 - 0:20 — the hook, no screen yet.**
"We had 55,558 raw intrusion-detection alerts across 8 attack scenarios. A human analyst
reviewing those one by one would drown. My system turns that into 1,395 ranked incidents, and
the #1 incident — a 3,842-alert scan-to-webshell burst — gets explained in plain English with a
confidence score, in about the time it took me to say this sentence."

**0:20 - 1:30 — live demo, Queue tab.**
- Open the queue. Point at the top chain, its score, alert count.
- Click it open. Point at the correlated alert timeline — "this one incident subsumed thousands
  of raw log lines."
- Click **Explain** (pre-warmed, instant). Read one line of the summary aloud. Point at
  confidence + the false-positive hypotheses — "it's not just classifying, it's telling me how it
  could be wrong."

**1:30 - 2:15 — the feedback loop, live.**
- Scroll to a near-bottom, single-detector, low-score chain.
- Click **Mark false positive.** Watch the queue count and suppressed count change on screen.
- "That's not a toggle, it's inferred live — flip the verdict back and the suppression clears on
  its own, no separate bookkeeping."

**2:15 - 2:45 — the honest part.**
"Two things this build is upfront about: raw severity alone is a bad ranking — benign high-entropy
DNS queries score exactly like real exfiltration — which is *why* the correlation and feedback
layers exist, not a bug I didn't get to. And ground truth doesn't cover every attack repetition,
so for the edge cases, the LLM and the analyst verdict are the arbiter — same as a real SOC."

**2:45 - 3:00 — close.**
"It's deployed, not just running on my laptop" (show the Azure URL for two seconds), "and it
ingests live data through the same pipeline, not just the static pack" — optionally fire
`demo_ingest.py` live if you have 30 seconds of Q&A slack, otherwise mention it and move on.

## Anticipated Q&A

**"What's your actual precision?"**
Raw per-alert precision is 80-93% across scenarios, but that's misleading — it's inflated by
massively-repeated true-positive signatures. After dedup, 4 of 8 scenarios (fox/harrison/
wheeler/wilson) hold at 85-88%; the other 4 (russellmitchell/santos/shaw/wardbeck) crash to
16-29%. That split *is* the finding, not a flaw I'm hiding.

**"Why does precision crash on exactly those 4?"**
Those scenarios have attack steps that fire the same true-positive signature thousands of times
(it dedupes to one representative) while benign one-off noise stays uncollapsed — so a handful of
false positives suddenly make up a much bigger share of a much smaller set. Raw accuracy was
flattering; dedup accuracy is honest. That's the whole argument for the correlation + feedback
layer on top: a single alert's precision is the wrong unit, an incident's is the right one.

**"How do you know your ranking isn't just lucky on this dataset?"**
I don't claim recall; I show the 2 honest caveats in the README/UI: high-entropy DNS floats
regardless of attack-step labels, and some exfil bursts fall outside labeled windows entirely.
Both are visible in "eval mode" in the live app, not hidden.

**"Why three cloud LLM providers instead of one?"**
Judging criteria said comfort with LLM tooling; I wanted to show the architecture is
provider-agnostic — same prompt, same JSON contract, swap Anthropic/OpenAI/Kimi K3/local Ollama
at the dropdown with zero code change on the backend. It's also a real reliability story: if one
vendor's API is down during judging, the demo doesn't die.

**"What happens with real production-scale data, not 55k alerts?"**
The correlation step is O(alerts × existing chains) per ingest batch — fine at this scale
(capped at 5,000/batch), not fine at enterprise SIEM volume without per-host indexing. I'd call
that out proactively if asked "what would you change for scale."

**"Is /api/ingest safe to expose?"**
It's gated behind a shared-secret header (`X-Ingest-Key`) once deployed — found and fixed that
gap myself before sharing the Azure URL, not after someone asked.

**"What was the hardest bug?"**
Zip-deploying to Azure App Service silently skips the real dependency-install step unless you
explicitly set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` — the deploy reports "success" in 4 seconds
while never actually installing pandas/flask, and the failure only shows up as an opaque
"worker failed to start" 10 minutes later. Found it by diffing deployment log timestamps.

**"What would you build with one more week?"**
Per-host indexing for ingest correlation (drop the O(n×m) scan), a second LLM pass that cross-
checks the first provider's verdict before auto-suppressing, and backfilling ground truth onto
the live-ingested chains instead of leaving `attack_steps_covered` empty for anything outside
the 8 labeled scenarios.

## If something breaks live

- **Explain hangs** → say "let's not wait on the network" out loud, switch the dropdown to a
  pre-warmed chain, keep moving. Never apologize more than once.
- **Azure URL is down** → you have localhost as a complete fallback; say so and switch, judges
  care that it *works*, not which URL.
- **A judge asks something you don't know** → "that's a fair gap — here's what I'd do to find
  out" beats a guess every time, especially solo, where there's no teammate to rescue you.
