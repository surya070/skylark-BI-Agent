const thread = document.getElementById("thread");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const send = document.getElementById("send");
const statusEl = document.getElementById("status");
const modelEl = document.getElementById("model");
const pulseEl = document.getElementById("pulse");
const funnelEl = document.getElementById("funnel-bars");
const overdueEl = document.getElementById("overdue-bars");
const backlogBody = document.querySelector("#backlog-table tbody");
const recvBody = document.querySelector("#recv-table tbody");
const backlogMore = document.getElementById("backlog-more");
const dashFresh = document.getElementById("dash-fresh");
const dashRefresh = document.getElementById("dash-refresh");

const history = [];

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Minimal safe markdown: headings, lists, bold/italic, paragraphs. No raw HTML. */
function renderMarkdown(src) {
  const lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let inList = false;

  const flushList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };

  const inline = (s) =>
    escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flushList();
      continue;
    }
    if (/^###\s+/.test(line)) {
      flushList();
      html.push(`<h3>${inline(line.replace(/^###\s+/, ""))}</h3>`);
      continue;
    }
    if (/^##\s+/.test(line)) {
      flushList();
      html.push(`<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`);
      continue;
    }
    if (/^#\s+/.test(line)) {
      flushList();
      html.push(`<h2>${inline(line.replace(/^#\s+/, ""))}</h2>`);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inline(line.replace(/^[-*]\s+/, ""))}</li>`);
      continue;
    }
    flushList();
    html.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  return html.join("");
}

function freshnessLabel(freshness) {
  if (!freshness || typeof freshness !== "object") return "";
  const parts = [];
  for (const [key, info] of Object.entries(freshness)) {
    if (!info || typeof info !== "object") continue;
    const age = info.fetched_seconds_ago != null ? `${Math.round(info.fetched_seconds_ago)}s ago` : "";
    const live = info.live === false ? "stale" : "live";
    const n = info.records != null ? `${info.records} rows` : "";
    parts.push(`${key}: ${[live, n, age].filter(Boolean).join(" · ")}`);
  }
  return parts.join(" · ");
}

function fmtMasked(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const abs = Math.abs(v);
  if (abs >= 1e7) return `${(v / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${(v / 1e5).toFixed(1)} L`;
  return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function fmtPct(rate) {
  if (rate == null) return "—";
  return `${(Number(rate) * 100).toFixed(0)}%`;
}

function fmtDate(value) {
  if (!value) return "—";
  const s = String(value);
  return s.length >= 10 ? s.slice(0, 10) : s;
}

function truncate(text, n = 42) {
  const s = String(text || "—");
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function scrollToComposer() {
  const ask = document.querySelector(".ask-zone");
  if (ask && window.matchMedia("(max-width: 1100px)").matches) {
    ask.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  input.focus();
}

function addMessage(role, text, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg-wrap ${role}`;

  const el = document.createElement("div");
  el.className = `msg ${role}${extraClass ? ` ${extraClass}` : ""}`;
  if (role === "bot" && !extraClass.includes("pending")) {
    el.classList.add("md");
    el.innerHTML = renderMarkdown(text);
  } else {
    el.textContent = text;
  }
  wrap.appendChild(el);
  thread.appendChild(wrap);
  thread.scrollTop = thread.scrollHeight;
  return { wrap, el };
}

function attachMeta(wrap, { tools_used, data_freshness, model }) {
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  const chips = [];
  if (tools_used && tools_used.length) {
    chips.push(`<span class="chip-meta">Tools: ${escapeHtml(tools_used.join(", "))}</span>`);
  }
  const fresh = freshnessLabel(data_freshness);
  if (fresh) {
    chips.push(`<span class="chip-meta">Data: ${escapeHtml(fresh)}</span>`);
  }
  if (model) {
    chips.push(`<span class="chip-meta">${escapeHtml(model)}</span>`);
  }
  if (!chips.length) return;
  meta.innerHTML = chips.join("");
  wrap.appendChild(meta);
}

function renderBars(container, items, { warn = false, labelKey = "label", countKey = "count" } = {}) {
  if (!items.length) {
    container.innerHTML = `<p class="bars-empty">Nothing to show.</p>`;
    return;
  }
  const max = Math.max(...items.map((i) => Number(i[countKey]) || 0), 1);
  container.innerHTML = items
    .map((item) => {
      const count = Number(item[countKey]) || 0;
      const pct = Math.max(4, Math.round((count / max) * 100));
      const label = escapeHtml(String(item[labelKey] || "—").replace(/_/g, " "));
      return `<div class="bar-row">
        <span class="bar-label" title="${label}">${label}</span>
        <div class="bar-track"><div class="bar-fill${warn ? " warn" : ""}" style="width:${pct}%"></div></div>
        <span class="bar-count">${count}</span>
      </div>`;
    })
    .join("");
}

function metricButton({ label, value, hint, ask, attention, okTone }) {
  const classes = ["metric"];
  if (attention) classes.push("attention");
  if (okTone) classes.push("ok-tone");
  return `<button type="button" class="${classes.join(" ")}" data-q="${escapeHtml(ask)}" role="listitem">
    <span class="metric-label">${escapeHtml(label)}</span>
    <span class="metric-value">${escapeHtml(value)}</span>
    <span class="metric-hint">${escapeHtml(hint)}</span>
  </button>`;
}

function renderDashboard(data) {
  const p = data.pulse || {};
  const overdue = Number(p.overdue_work_orders) || 0;
  const wonGap = Number(p.won_deals_without_work_order) || 0;

  pulseEl.innerHTML = [
    metricButton({
      label: "Open deals",
      value: String(p.open_deals ?? "—"),
      hint: `${p.total_deals ?? "—"} total · win ${fmtPct(p.win_rate_of_decided_deals)}`,
      ask: "Across all deals (no date filter): how is overall pipeline looking — open deals, win rate, and open pipeline value?",
    }),
    metricButton({
      label: "Open pipeline",
      value: fmtMasked(p.open_pipeline_value_masked),
      hint: "Masked deal value · open stages",
      ask: "Across all deals (no date filter): what is open pipeline value by sector and closure probability?",
    }),
    metricButton({
      label: "Overdue WOs",
      value: String(overdue),
      hint: "Past probable end · not completed",
      ask: "Which work orders are past end date but not completed? Summarise by sector and status.",
      attention: overdue > 0,
      okTone: overdue === 0,
    }),
    metricButton({
      label: "Receivables",
      value: fmtMasked(p.receivables_total_masked),
      hint: wonGap
        ? `${wonGap} won deals with no work order`
        : `${p.total_work_orders ?? "—"} work orders`,
      ask: "Across all work orders (no date filter): summarise receivables and the largest collection exposures.",
      attention: Number(p.receivables_total_masked) > 0,
    }),
  ].join("");

  renderBars(
    funnelEl,
    (data.funnel || []).map((f) => ({ label: f.bucket, count: f.count })),
  );
  renderBars(
    overdueEl,
    (data.overdue_by_sector || []).map((f) => ({ label: f.sector, count: f.count })),
    { warn: true },
  );

  const backlogRows = data.backlog?.rows || [];
  backlogBody.innerHTML = backlogRows.length
    ? backlogRows
        .map((row) => {
          const name = truncate(row.name || row.serial || "Untitled");
          const q = `Tell me about work order “${String(row.name || row.serial || "").replace(/"/g, "")}” — status, sector, and slippage.`;
          return `<tr>
            <td><button type="button" class="row-ask" data-q="${escapeHtml(q)}">${escapeHtml(name)}</button></td>
            <td>${escapeHtml(row.sector || "—")}</td>
            <td>${escapeHtml(row.status || "—")}</td>
            <td class="num muted">${escapeHtml(fmtDate(row.end_date))}</td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="4" class="muted">No overdue work orders.</td></tr>`;

  if (data.backlog?.has_more) {
    backlogMore.hidden = false;
    backlogMore.textContent = `Showing ${backlogRows.length} of ${data.backlog.total}. Use “Ask full list” for the rest.`;
  } else {
    backlogMore.hidden = true;
  }

  const recvRows = data.receivables?.rows || [];
  recvBody.innerHTML = recvRows.length
    ? recvRows
        .map((row) => {
          const name = truncate(row.name || "Untitled");
          const q = `What is the receivable and collection status for work order “${String(row.name || "").replace(/"/g, "")}”?`;
          return `<tr>
            <td><button type="button" class="row-ask" data-q="${escapeHtml(q)}">${escapeHtml(name)}</button></td>
            <td>${escapeHtml(row.sector || "—")}</td>
            <td class="num">${escapeHtml(fmtMasked(row.receivable_masked))}</td>
            <td class="muted">${escapeHtml(row.collection_status || "—")}</td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="4" class="muted">No receivable exposures with values.</td></tr>`;

  const fresh = freshnessLabel(data.data_freshness);
  dashFresh.textContent = fresh
    ? `Live from monday.com · ${fresh}`
    : "Live from monday.com · amounts masked";
}

async function loadDashboard() {
  dashRefresh.disabled = true;
  try {
    const res = await fetch("/api/dashboard");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Dashboard failed");
    renderDashboard(data);
  } catch (err) {
    dashFresh.textContent = `Could not load pulse: ${err.message || err}`;
    pulseEl.innerHTML = "";
  } finally {
    dashRefresh.disabled = false;
  }
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (!res.ok && data.monday === "unavailable") {
      throw new Error(data.error || "Health check failed");
    }
    const deals = data.deals?.records ?? "?";
    const orders = data.work_orders?.records ?? "?";
    const degraded = data.monday !== "connected";
    statusEl.className = `status ${degraded ? "bad" : "ok"}`;
    statusEl.textContent = degraded
      ? `monday.com ${data.monday} · cached snapshot`
      : `monday.com live · ${deals} deals · ${orders} WOs`;
    modelEl.textContent = data.model_configured
      ? `Model: ${data.model}`
      : "Model: not configured";
  } catch (err) {
    statusEl.className = "status bad";
    statusEl.textContent = `Connection issue: ${err.message || err}`;
  }
}

async function ask(message) {
  const text = message.trim();
  if (!text) return;

  scrollToComposer();
  addMessage("user", text);
  history.push({ role: "user", content: text });
  input.value = "";
  send.disabled = true;
  const pending = addMessage("bot", "Working with live monday.com data…", "pending");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: history.slice(0, -1) }),
    });
    const data = await res.json();
    if (!res.ok && res.status !== 429) {
      throw new Error(data.detail || data.error || data.reply || "Chat failed");
    }
    pending.el.classList.remove("pending");
    pending.el.classList.add("md");
    pending.el.innerHTML = renderMarkdown(data.reply || "");
    attachMeta(pending.wrap, data);
    history.push({ role: "assistant", content: data.reply || "" });
  } catch (err) {
    pending.el.classList.remove("pending");
    pending.el.textContent = `Error: ${err.message || err}`;
  } finally {
    send.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  ask(input.value);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => ask(chip.dataset.q || chip.textContent));
});

document.getElementById("dashboard").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-q]");
  if (!btn || !btn.dataset.q) return;
  ask(btn.dataset.q);
});

dashRefresh.addEventListener("click", () => {
  loadDashboard();
  checkHealth();
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

addMessage(
  "meta",
  "Scan the pulse above first. Ask here when you need a brief, an odd cut, or the story behind a metric.",
);
checkHealth();
loadDashboard();
