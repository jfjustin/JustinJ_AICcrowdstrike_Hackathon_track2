const state = {
  chains: [],
  selectedId: null,
  scenarios: [],
};

const el = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const PROVIDERS = {
  "ollama-deepseek": { label: "Private — Ollama (deepseek-r1:8b)", cloud: false, provider: "ollama", model: "deepseek-r1:8b" },
  "ollama-gptoss": { label: "Private — Ollama (gpt-oss:20b)", cloud: false, provider: "ollama", model: "gpt-oss:20b" },
  anthropic: { label: "Cloud — Anthropic API", cloud: true, provider: "anthropic", placeholder: "sk-ant-... (used once, kept only in this tab)" },
  openai: { label: "Cloud — OpenAI API", cloud: true, provider: "openai", placeholder: "sk-... (used once, kept only in this tab)" },
  kimi: { label: "Cloud — Kimi K3 (Moonshot)", cloud: true, provider: "kimi", placeholder: "Moonshot API key (used once, kept only in this tab)" },
};

// ---------- tabs ----------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    el(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "metrics") loadMetrics();
  });
});

// ---------- queue ----------
function queueParams() {
  const params = new URLSearchParams();
  const scenario = el("#scenario-filter").value;
  const minScore = el("#min-score").value;
  if (scenario) params.set("scenario", scenario);
  if (minScore) params.set("min_score", minScore);
  if (el("#show-suppressed").checked) params.set("show_suppressed", "true");
  if (el("#eval-mode").checked) params.set("eval", "1");
  return params;
}

async function loadChains() {
  const res = await fetch(`/api/chains?${queueParams()}`);
  const data = await res.json();
  state.chains = data.chains;
  state.scenarios = data.scenarios;

  const sel = el("#scenario-filter");
  const current = sel.value;
  sel.innerHTML = '<option value="">All scenarios</option>' +
    data.scenarios.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  sel.value = current;

  el("#queue-count").textContent = `${data.total_visible} visible, ${data.total_suppressed} suppressed`;
  renderRows();
}

function fmtWindow(c) {
  const s = (c.start_iso || "").replace("T", " ").replace("Z", "");
  const e = (c.end_iso || "").replace("T", " ").replace("Z", "");
  return `${s} → ${e}`;
}

function verdictBadge(v) {
  if (!v) return "";
  const cls = { TRUE_POSITIVE: "tp", FALSE_POSITIVE: "fp", NEEDS_REVIEW: "review" }[v] || "review";
  return `<span class="badge ${cls}">${esc(v)}</span>`;
}

function renderRows() {
  const tbody = el("#chain-rows");
  tbody.innerHTML = state.chains
    .map((c) => {
      const steps = (c.attack_steps_covered || [])
        .map((s) => `<span>${esc(s)}</span>`)
        .join("");
      const selected = c.chain_id === state.selectedId ? "selected" : "";
      const suppressed = c.suppressed ? "suppressed" : "";
      const evalFlag = c.likely_true_positive !== undefined
        ? ` <span class="muted">(gt: ${c.likely_true_positive ? "TP" : "noise"})</span>`
        : "";
      return `<tr class="${selected} ${suppressed}" data-id="${esc(c.chain_id)}">
        <td><span class="score-pill">${Math.round(c.chain_score)}</span></td>
        <td>${esc(c.scenario)}</td>
        <td>${esc(c.host)}</td>
        <td class="muted">${fmtWindow(c)}</td>
        <td>${c.alert_count}${evalFlag}</td>
        <td class="steps-chips">${steps}</td>
        <td>${verdictBadge(c.analyst_verdict)}</td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => selectChain(tr.dataset.id));
  });
}

// ---------- detail panel ----------
async function selectChain(chainId) {
  state.selectedId = chainId;
  renderRows();
  const evalMode = el("#eval-mode").checked ? "?eval=1" : "";
  const res = await fetch(`/api/chains/${encodeURIComponent(chainId)}${evalMode}`);
  if (!res.ok) return;
  const chain = await res.json();
  renderDetail(chain);
}

function renderExplanation(result) {
  if (!result) return "";
  const fps = (result.false_positive_hypotheses || []).map((h) => `<li>${esc(h)}</li>`).join("");
  const steps = (result.next_steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
  return `<div class="explanation-box">
    <span class="provider-tag">${esc(result.provider || "")}</span>
    <div class="summary">${esc(result.summary)}</div>
    <div><strong>Confidence:</strong> ${esc(result.confidence)} — <span class="muted">${esc(result.confidence_why)}</span></div>
    <div><strong>False-positive hypotheses</strong><ul>${fps}</ul></div>
    <div><strong>Next steps</strong><ul>${steps}</ul></div>
    <div>${verdictBadge(result.verdict)}</div>
  </div>`;
}

function renderDetail(chain) {
  const alertLines = (chain.context_alerts || [])
    .map((a) => `<div class="alert-line">[${esc(a.ts_iso)}] sev=${esc(a.severity)} ${esc(a.detector)}: ${esc(a.message)}</div>`)
    .join("");

  const suppressNote = chain.suppressed
    ? `<div class="muted">Suppressed: ${esc(chain.suppression_reason || "matches an analyst-marked false-positive signature")}
       — <button class="link-btn" id="unsuppress-btn">unsuppress</button></div>`
    : "";

  const cached = chain.cached_explanations || {};
  const cachedHtml = Object.keys(cached).length
    ? `<div><strong>Cached explanations</strong>${Object.values(cached).map(renderExplanation).join("")}</div>`
    : "";

  el("#detail-panel").innerHTML = `
    <h3>${esc(chain.chain_id)} — ${esc(chain.scenario)}</h3>
    <div class="meta-row">
      host ${esc(chain.host)} · ${fmtWindow(chain)} · ${chain.alert_count} alerts ·
      max severity ${esc(chain.max_severity)} · score ${Math.round(chain.chain_score)}
      ${chain.likely_true_positive !== undefined ? `· ground truth: ${chain.likely_true_positive ? "TRUE POSITIVE" : "noise"}` : ""}
    </div>
    ${suppressNote}

    <div class="provider-row">
      <select id="provider-select">
        ${Object.entries(PROVIDERS).map(([value, p]) => `<option value="${value}">${esc(p.label)}</option>`).join("")}
      </select>
      <input id="api-key-input" type="password" placeholder="" style="display:none" />
      <button class="explain-btn" id="explain-btn">Explain</button>
    </div>
    <div id="explain-status" class="muted"></div>
    <div id="explain-result"></div>

    <div class="provider-row">
      <button class="verdict-btn tp" data-verdict="TRUE_POSITIVE">Confirm incident</button>
      <button class="verdict-btn fp" data-verdict="FALSE_POSITIVE">Mark false positive</button>
      <button class="verdict-btn review" data-verdict="NEEDS_REVIEW">Needs review</button>
    </div>

    <h4>Context alerts (top ${chain.context_alerts?.length || 0} by severity)</h4>
    ${alertLines}
    ${cachedHtml}
  `;

  const providerSelect = el("#provider-select");
  const syncKeyInput = () => {
    const meta = PROVIDERS[providerSelect.value];
    const keyInput = el("#api-key-input");
    keyInput.style.display = meta.cloud ? "block" : "none";
    keyInput.placeholder = meta.placeholder || "";
    keyInput.value = meta.cloud ? sessionStorage.getItem(`${providerSelect.value}_api_key`) || "" : "";
  };
  providerSelect.addEventListener("change", syncKeyInput);
  syncKeyInput();

  el("#explain-btn").addEventListener("click", () => explainChain(chain.chain_id));

  document.querySelectorAll(".verdict-btn").forEach((btn) => {
    btn.addEventListener("click", () => submitVerdict(chain.chain_id, btn.dataset.verdict));
  });

  const unsuppressBtn = el("#unsuppress-btn");
  if (unsuppressBtn) {
    unsuppressBtn.addEventListener("click", async () => {
      await fetch(`/api/chains/${encodeURIComponent(chain.chain_id)}/unsuppress`, { method: "POST" });
      loadChains();
      selectChain(chain.chain_id);
    });
  }
}

async function explainChain(chainId) {
  const providerKey = el("#provider-select").value;
  const meta = PROVIDERS[providerKey];
  const statusEl = el("#explain-status");
  const resultEl = el("#explain-result");
  const body = { provider: meta.provider, cache_key: providerKey };
  if (meta.model) body.model = meta.model;

  if (meta.cloud) {
    const key = el("#api-key-input").value.trim();
    if (!key) {
      statusEl.textContent = `Paste a ${meta.label.split("— ")[1]} key first.`;
      return;
    }
    sessionStorage.setItem(`${providerKey}_api_key`, key);
    body.api_key = key;
  }

  statusEl.textContent = "Asking the model…";
  resultEl.innerHTML = "";
  try {
    const res = await fetch(`/api/chains/${encodeURIComponent(chainId)}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await res.json();
    statusEl.textContent = result.provider === "fallback" ? "Model unreachable — showing offline fallback." : "";
    resultEl.innerHTML = renderExplanation(result);
  } catch (err) {
    statusEl.textContent = `Error: ${err}`;
  }
}

async function submitVerdict(chainId, verdict) {
  await fetch(`/api/chains/${encodeURIComponent(chainId)}/verdict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict }),
  });
  await loadChains();
  selectChain(chainId);
}

// ---------- metrics ----------
function barRow(label, value, max) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  return `<div class="bar-row">
    <div class="bar-label">${esc(label)}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
    <div class="bar-value">${value}</div>
  </div>`;
}

async function loadMetrics() {
  const res = await fetch("/api/metrics");
  const m = await res.json();
  const v = m.volume;
  const p = m.precision_at_k;

  const headline = m.headline_chain
    ? `<div class="headline-card">
        <strong>${esc(m.headline_chain.alert_count)} alerts → 1 incident.</strong>
        ${esc(m.headline_chain.chain_id)} on ${esc(m.headline_chain.host)}
        (${esc(m.headline_chain.scenario)}): ${esc((m.headline_chain.attack_steps_covered || []).join(" → "))}.
      </div>`
    : "";

  const scenarioRows = Object.entries(m.baseline_by_scenario)
    .map(([name, s]) => `<tr>
      <td>${esc(name)}</td><td>${s.alerts_raw}</td><td>${s.alerts_after_dedup}</td>
      <td>${s.precision_raw_pct}%</td><td>${s.precision_after_dedup_pct}%</td>
      <td>${s.chains}</td><td>${s.attack_steps_covered_by_chains}/${s.attack_steps}</td>
    </tr>`)
    .join("");

  el("#metrics-content").innerHTML = `
    ${headline}
    <div class="metrics-grid">
      <div class="metric-card"><div class="value">${v.raw_alerts.toLocaleString()}</div><div class="label">raw alerts</div></div>
      <div class="metric-card"><div class="value">${v.deduped_alerts.toLocaleString()}</div><div class="label">after dedup</div></div>
      <div class="metric-card"><div class="value">${v.chains_before_feedback}</div><div class="label">correlated chains</div></div>
      <div class="metric-card"><div class="value">${v.chains_after_feedback}</div><div class="label">chains after feedback loop</div></div>
      <div class="metric-card"><div class="value">${v.suppressed_count}</div><div class="label">suppressed by analyst feedback</div></div>
    </div>

    <h3>Precision@${m.k}: before vs after feedback loop</h3>
    <div class="bar-compare">
      ${barRow("Before", p.before ?? 0, 100)}
      ${barRow("After", p.after ?? 0, 100)}
    </div>

    <h3>Baseline by scenario (from the data pack's evaluation.json)</h3>
    <table class="eval-table">
      <thead><tr><th>scenario</th><th>raw</th><th>deduped</th><th>prec. raw</th><th>prec. deduped</th><th>chains</th><th>steps covered</th></tr></thead>
      <tbody>${scenarioRows}</tbody>
    </table>
  `;
}

el("#refresh-btn").addEventListener("click", loadChains);
el("#reset-btn").addEventListener("click", async () => {
  if (!confirm("Clear all analyst verdicts and cached explanations?")) return;
  await fetch("/api/reset", { method: "POST" });
  state.selectedId = null;
  el("#detail-panel").innerHTML = '<p class="muted">Select an incident from the queue to see the correlated alerts and generate an explanation.</p>';
  await loadChains();
});
el("#scenario-filter").addEventListener("change", loadChains);
el("#show-suppressed").addEventListener("change", loadChains);
el("#eval-mode").addEventListener("change", loadChains);

loadChains();
