const EXAMPLES = [
  "What did GAO find about FEMA's disaster workforce?",
  "How many major disaster declarations has Florida had since 2017?",
  "Who is eligible for FEMA Individual Assistance home repair help?",
  "How have overdose deaths changed in Maryland since 2022?",
];

const $ = (sel) => document.querySelector(sel);
let selectedSources = null; // null = all
let lastSegments = [];

// ---------- tabs
document.querySelectorAll("button.tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("button.tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${btn.dataset.view}`).classList.remove("hidden");
    if (btn.dataset.view === "evals") loadEvals();
  });
});

// ---------- source chips
document.querySelectorAll("#source-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const all = chip.dataset.source === "all";
    if (all) {
      document.querySelectorAll("#source-chips .chip").forEach((c) => c.classList.toggle("on", c === chip));
    } else {
      chip.classList.toggle("on");
      document.querySelector('.chip[data-source="all"]').classList.remove("on");
    }
    const on = [...document.querySelectorAll("#source-chips .chip.on")].map((c) => c.dataset.source);
    if (!on.length || on.includes("all")) {
      selectedSources = null;
      document.querySelector('.chip[data-source="all"]').classList.add("on");
    } else {
      selectedSources = on;
    }
  });
});

// ---------- examples
EXAMPLES.forEach((q) => {
  const b = document.createElement("button");
  b.className = "example";
  b.textContent = q;
  b.onclick = () => { $("#q").value = q; ask(); };
  $("#examples").appendChild(b);
});

$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask(); });
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Tiny markdown: paragraphs, bullet lists, bold. Citation markers are spliced in as placeholders first.
function renderMarkdown(text) {
  const lines = esc(text).split("\n");
  let html = "", inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)/) || line.match(/^\d+\.\s+(.*)/);
    if (bullet) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${bullet[1]}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (!line) continue;
    const h = line.match(/^#{1,4}\s+(.*)/);
    html += h ? `<h4>${h[1]}</h4>` : `<p>${line}</p>`;
  }
  if (inList) html += "</ul>";
  return html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function renderAnswer(segments) {
  let text = "";
  for (const seg of segments) {
    text += seg.text;
    const ns = [...new Set((seg.citations || []).map((c) => c.n))];
    if (ns.length) text += ns.map((n) => `⁣${n}⁣`).join("");
  }
  return renderMarkdown(text).replace(/⁣(\d+)⁣/g,
    (_, n) => `<a class="cite" href="#src-${n}" data-n="${n}">${n}</a>`);
}

const BADGES = {
  verified: ["Verified", "Every claim is cited and the citations check out."],
  partially_supported: ["Partly supported", "Some sentences or numbers aren't backed by a citation. Check the sources."],
  declined: ["Not in sources", "The indexed sources don't answer this, so FedSight didn't guess."],
  unsupported: ["Unsupported", "The answer couldn't be tied to sources."],
  blocked_input: ["Blocked", "This looked like an attempt to change the assistant's instructions."],
};

function setStatus(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.toggle("hidden", !msg);
  el.classList.toggle("error", isError);
}

async function ask() {
  const question = $("#q").value.trim();
  if (question.length < 3) return;
  $("#ask-btn").disabled = true;
  $("#result").classList.add("hidden");
  setStatus("Searching the sources…");
  const slow = setTimeout(() => setStatus("Reading passages and checking citations…"), 4000);
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, sources: selectedSources }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.detail || `Request failed (${res.status})`);
    showResult(data);
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    clearTimeout(slow);
    $("#ask-btn").disabled = false;
  }
}

function showResult(d) {
  lastSegments = d.segments || [];
  const g = d.guardrails || {};
  const [label, tip] = BADGES[g.status] || ["Answer", ""];
  const badge = $("#badge");
  badge.textContent = label;
  badge.title = tip;
  badge.className = `badge ${g.status || ""}`;
  const u = d.usage || {};
  const cost = u.cost_usd ? ` · $${u.cost_usd.toFixed(4)}` : "";
  $("#meta").textContent = `${(u.latency_ms / 1000 || 0).toFixed(1)}s · ${u.llm_calls || 0} model calls${cost}`;
  $("#answer").innerHTML = renderAnswer(d.segments || []);

  const cited = (d.sources || []).filter((s) => s.cited_as);
  const other = (d.sources || []).filter((s) => !s.cited_as);
  $("#sources").innerHTML = cited.map(sourceCard).join("") +
    (other.length ? `<li class="also">Also read but not cited: ${other.map((s) => esc(s.title)).join(" · ")}</li>` : "");
  if (!cited.length && !other.length) $("#sources").innerHTML = `<li class="also">No sources were used.</li>`;

  $("#steps").innerHTML = (d.steps || []).map((s) => `
    <li class="${s.ok ? "" : "bad"}">
      <code>${esc(s.tool)}</code>
      <div class="step-input">${esc(s.input.query || s.input.sql || JSON.stringify(s.input))}</div>
      <div class="step-sum">${esc(s.summary)} · ${s.ms} ms</div>
    </li>`).join("") || "<li>No tools were called.</li>";

  const checks = [
    ["Citations verified against source text", g.citations_total ? `${g.citations_total - g.citations_invalid}/${g.citations_total}` : "—", !g.citations_invalid],
    ["Share of answer backed by citations", g.coverage != null ? `${Math.round(g.coverage * 100)}%` : "—", (g.coverage ?? 1) >= 0.6],
    ["Numbers found in the evidence", g.unsupported_numbers?.length ? `unsupported: ${g.unsupported_numbers.join(", ")}` : "all", !g.unsupported_numbers?.length],
    ["Personal info redacted from question", g.input_pii_redacted?.length ? g.input_pii_redacted.join(", ") : "none found", true],
    ["Prompt-injection screen", g.injection_score >= 0.6 ? "blocked" : "passed", g.injection_score < 0.6],
  ];
  $("#checks").innerHTML = checks.map(([k, v, ok]) =>
    `<li class="${ok ? "ok" : "warn"}"><span>${k}</span><b>${esc(v)}</b></li>`).join("");

  $("#result").classList.remove("hidden");
  document.querySelectorAll("a.cite").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const el = document.getElementById(`src-${a.dataset.n}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1200);
  }));
}

function quotesFor(s, segments) {
  // the exact passages the answer leaned on
  const out = new Set();
  for (const seg of segments || []) for (const c of seg.citations || []) if (c.source === s.source) out.add(c.cited_text);
  return [...out];
}

function sourceCard(s) {
  const quotes = quotesFor(s, lastSegments).slice(0, 3);
  const q = quotes.map((t) => `<blockquote>${esc(t)}</blockquote>`).join("");
  if (s.kind === "data") {
    const rows = (s.rows || []).slice(0, 8);
    const table = s.columns?.length ? `<div class="table-scroll"><table><thead><tr>${s.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    return `<li id="src-${s.cited_as}" class="source data">
      <div class="src-head"><span class="n">${s.cited_as}</span><span class="tag">DATA</span><strong>${esc(s.title)}</strong></div>
      <pre class="sql">${esc(s.sql)}</pre>${table}</li>`;
  }
  const tag = (s.source_type || "").toUpperCase();
  return `<li id="src-${s.cited_as}" class="source">
    <div class="src-head"><span class="n">${s.cited_as}</span><span class="tag ${s.source_type}">${tag}</span>
      <strong>${esc(s.title)}</strong></div>
    ${q}
    <a class="open" href="${esc(s.url || s.source)}" target="_blank" rel="noopener">Open source${s.page ? ` at page ${s.page}` : ""} ↗</a>
  </li>`;
}

// ---------- evals tab
let evalsLoaded = false;
async function loadEvals() {
  if (evalsLoaded) return;
  try {
    const res = await fetch("/api/evals");
    if (!res.ok) throw new Error("No evaluation results published yet.");
    const d = await res.json();
    evalsLoaded = true;
    const m = d.summary || {};
    const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
    const rows = [
      ["Answer correctness (key facts present, judged)", pct(m.answer_correct)],
      ["Faithfulness (claims supported by cited text, judged)", pct(m.faithful)],
      ["Citations that match the source text", pct(m.citation_valid)],
      ["Retrieval: right document in top 6", pct(m.retrieval_hit_at_k)],
      ["Unanswerable questions correctly declined", pct(m.declined_when_unanswerable)],
      ["Prompt-injection attempts resisted", pct(m.injection_resisted)],
      ["Data questions with the correct number", pct(m.data_correct)],
      ["Median latency", m.latency_p50_s != null ? `${m.latency_p50_s.toFixed(1)} s` : "—"],
      ["Average cost per question", m.cost_per_question != null ? `$${m.cost_per_question.toFixed(4)}` : "—"],
    ];
    $("#evals-body").innerHTML = `
      <p class="fine">Run ${esc(m.run_at)} · ${m.n_questions} questions · answer model ${esc(m.answer_model)} · judge ${esc(m.judge_model)}</p>
      <table class="scorecard"><tbody>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</tbody></table>
      ${m.by_category ? `<h3>By question type</h3><table class="scorecard small"><thead><tr><th>Type</th><th>n</th><th>Passed</th></tr></thead><tbody>
        ${Object.entries(m.by_category).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.passed} (${pct(v.passed / v.n)})</td></tr>`).join("")}</tbody></table>` : ""}`;
  } catch (err) {
    $("#evals-body").textContent = err.message;
  }
}
