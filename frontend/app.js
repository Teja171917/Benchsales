/* BenchPilot frontend — vanilla JS. */
const $ = (sel, el) => (el || document).querySelector(sel);
const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

async function api(path, opts) {
  const r = await fetch(path, Object.assign(
    {headers: {"Content-Type": "application/json"}}, opts || {}));
  const txt = await r.text();
  let data = null;
  try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = {raw: txt}; }
  if (!r.ok) throw new Error((data && data.detail) || ("HTTP " + r.status));
  return data;
}

const STATUSES = ["queued", "applied", "screening", "interview",
  "offered", "placed", "rejected", "withdrawn"];
const STATUS_LABEL = {queued: "Queued", applied: "Applied",
  screening: "Screening", interview: "Interview", offered: "Offered",
  placed: "Placed", rejected: "Rejected", withdrawn: "Withdrawn"};

/* ---------- tab nav ---------- */
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$("main .tab").forEach((t) => t.classList.toggle("active",
    t.id === "tab-" + b.dataset.tab));
  render(b.dataset.tab);
});
function go(tab) { $(`#tabs button[data-tab="${tab}"]`).click(); }

/* ---------- modal ---------- */
function openModal(html, wide) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-back"><div class="modal${wide ? " wide" : ""}">${html}</div></div>`;
  $(".modal-back", root).addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-back")) closeModal();
  });
}
function closeModal() { $("#modal-root").innerHTML = ""; }

/* ================= CONSULTANTS ================= */
async function renderConsultants() {
  const el = $("#tab-consultants");
  el.innerHTML = `<div class="row spread"><h2>Consultants</h2>
    <button class="btn primary" id="c-add">Add consultant</button></div>
    <div id="c-list" class="grid"><span class="muted">Loading…</span></div>`;
  $("#c-add").onclick = () => consultantModal(null);
  const list = await api("/api/consultants");
  $("#c-list").innerHTML = list.map((c) => `
    <div class="card">
      <div class="row spread"><h3>${esc(c.name)}</h3>
        <span class="row">
          <button class="btn" data-edit="${c.id}">Edit</button>
          <button class="btn danger" data-del="${c.id}">Remove</button>
        </span></div>
      <div class="muted">${esc(c.location)}${c.visa_status ? " · " + esc(c.visa_status) : ""}</div>
      <div class="muted">${esc(c.email)}${c.phone ? " · " + esc(c.phone) : ""}</div>
      <div style="margin:8px 0">
        ${c.has_resume
          ? `<span class="badge">resume: ${esc(c.resume_filename)}</span>
             <div style="margin-top:6px">${c.skills.map((s) => `<span class="chip">${esc(s)}</span>`).join("") || '<span class="muted">no skills parsed</span>'}</div>`
          : `<span class="muted">no resume yet</span>`}
      </div>
      <div class="row">
        <label class="btn">Upload resume
          <input type="file" data-upload="${c.id}" accept=".pdf,.docx,.txt" hidden>
        </label>
        <span class="muted" data-uploadmsg="${c.id}"></span>
      </div>
    </div>`).join("") || `<div class="card muted">No consultants yet. Add your bench consultants above.</div>`;

  $$("[data-edit]", el).forEach((b) => b.onclick = async () => {
    const c = await api(`/api/consultants/${b.dataset.edit}`);
    consultantModal(c);
  });
  $$("[data-del]", el).forEach((b) => b.onclick = async () => {
    if (!confirm("Remove this consultant and their resume, matches and applications?")) return;
    await api(`/api/consultants/${b.dataset.del}`, {method: "DELETE"});
    renderConsultants();
  });
  $$("[data-upload]", el).forEach((inp) => inp.onchange = async () => {
    const cid = inp.dataset.upload;
    const msg = $(`[data-uploadmsg="${cid}"]`);
    const f = inp.files[0];
    if (!f) return;
    msg.textContent = "uploading…";
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await fetch(`/api/consultants/${cid}/resume`, {method: "POST", body: fd});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "upload failed");
      msg.textContent = `parsed ${d.skills.length} skills`;
      renderConsultants();
    } catch (e) { msg.textContent = "error: " + e.message; }
  });
}

function consultantModal(c) {
  c = c || {};
  openModal(`
    <h2>${c.id ? "Edit" : "Add"} consultant</h2>
    <div class="kv">
      <label>Name *</label><input type="text" id="m-name" value="${esc(c.name || "")}">
      <label>Email</label><input type="email" id="m-email" value="${esc(c.email || "")}">
      <label>Phone</label><input type="text" id="m-phone" value="${esc(c.phone || "")}">
      <label>Location</label><input type="text" id="m-location" value="${esc(c.location || "")}" placeholder="Houston, TX">
      <label>Visa status</label><input type="text" id="m-visa" value="${esc(c.visa_status || "")}" placeholder="H1B / GC / Citizen">
      <label>LinkedIn URL</label><input type="url" id="m-li" value="${esc(c.linkedin_url || "")}">
      <label>Notes</label><textarea id="m-notes" rows="2">${esc(c.notes || "")}</textarea>
    </div>
    <div class="row"><button class="btn primary" id="m-save">Save</button>
    <button class="btn" id="m-cancel">Cancel</button></div>`);
  $("#m-cancel").onclick = closeModal;
  $("#m-save").onclick = async () => {
    const data = {name: $("#m-name").value, email: $("#m-email").value,
      phone: $("#m-phone").value, location: $("#m-location").value,
      visa_status: $("#m-visa").value, linkedin_url: $("#m-li").value,
      notes: $("#m-notes").value};
    if (c.id) await api(`/api/consultants/${c.id}`, {method: "PUT", body: JSON.stringify(data)});
    else await api("/api/consultants", {method: "POST", body: JSON.stringify(data)});
    closeModal();
    renderConsultants();
  };
}

/* ================= JOBS ================= */
let jobsFilter = {source: "", q: ""};
async function renderJobs() {
  const el = $("#tab-jobs");
  el.innerHTML = `
    <div class="row spread"><h2>Jobs</h2>
      <button class="btn primary" id="j-run">Run job collection</button></div>
    <div class="progress" id="j-prog"></div>
    <div class="card"><h3>Live job search</h3>
      <div class="muted" style="margin-bottom:8px">Type a job title — BenchPilot searches the boards right now and shows listings instantly.</div>
      <div class="row">
        <input type="text" id="j-live-title" placeholder="job title, e.g. AI test engineer" style="flex:2;min-width:220px">
        <input type="text" id="j-live-loc" placeholder="location, e.g. Texas (optional)" style="flex:1;min-width:160px">
        <button class="btn primary" id="j-live-go">Search live</button></div>
      <div id="j-live-status" class="muted" style="margin-top:6px"></div>
      <div id="j-live-results" style="margin-top:8px"></div></div>
    <div class="card"><h3>Import a posting URL</h3>
      <div class="muted" style="margin-bottom:8px">Paste any LinkedIn, Indeed, Dice or company posting link — BenchPilot fetches and parses it.</div>
      <div class="row"><input type="url" id="j-url" placeholder="https://…" style="flex:1;min-width:280px">
      <button class="btn" id="j-import">Import</button></div>
      <div id="j-importmsg" class="muted" style="margin-top:6px"></div></div>
    <div class="card"><div class="row">
      <select id="j-source"><option value="">All sources</option></select>
      <input type="text" id="j-q" placeholder="search title/company…" value="${esc(jobsFilter.q)}">
      <button class="btn" id="j-search">Search</button></div></div>
    <div id="j-list"></div>`;
  $("#j-run").onclick = runCollection;
  $("#j-import").onclick = async () => {
    const url = $("#j-url").value.trim();
    const msg = $("#j-importmsg");
    if (!url) return;
    msg.textContent = "importing…";
    try {
      const j = await api("/api/jobs/import-url",
        {method: "POST", body: JSON.stringify({url})});
      msg.innerHTML = j.duplicate
        ? "Already in the database (duplicate skipped)."
        : `Imported: <b>${esc(j.title)}</b> — ${esc(j.company)}`;
      loadJobs();
    } catch (e) { msg.textContent = "error: " + e.message; }
  };
  const srcs = await api("/api/sources/status");
  $("#j-source").innerHTML = `<option value="">All sources</option>` +
    srcs.filter((s) => s.name !== "urlimport")
      .map((s) => `<option value="${s.name}"${jobsFilter.source === s.name ? " selected" : ""}>${esc(s.label)}</option>`).join("");
  $("#j-source").onchange = (e) => { jobsFilter.source = e.target.value; loadJobs(); };
  $("#j-search").onclick = () => { jobsFilter.q = $("#j-q").value; loadJobs(); };
  $("#j-q").onkeydown = (e) => { if (e.key === "Enter") $("#j-search").click(); };
  /* live title search */
  let liveResults = [];
  const doLiveSearch = async () => {
    const title = $("#j-live-title").value.trim();
    const location = $("#j-live-loc").value.trim();
    const st = $("#j-live-status"), box = $("#j-live-results");
    if (!title) { st.textContent = "Type a job title first."; return; }
    st.textContent = "Searching the boards… (10–30 seconds)";
    box.innerHTML = "";
    try {
      const r = await api("/api/jobs/live-search",
        {method: "POST", body: JSON.stringify({title, location})});
      liveResults = r.jobs;
      st.innerHTML = Object.values(r.sources)
        .map((s) => `${esc(s.label)}: ${esc(s.status)}${s.count ? ` (${s.count})` : ""}`)
        .join(" · ");
      if (!liveResults.length) {
        box.innerHTML = `<div class="muted">No listings found. Try a broader title — and add the free Adzuna API key in Settings for much wider coverage.</div>`;
        return;
      }
      box.innerHTML = `
        <div class="row spread" style="margin:8px 0"><b>${liveResults.length} listings</b>
          <button class="btn primary" id="j-live-saveall">Save all to job board</button></div>
        <div class="card" style="padding:0"><table class="jobs">
          <tr><th>Title</th><th>Company</th><th>Location</th><th>Source</th><th></th></tr>
          ${liveResults.map((j, i) => `<tr>
            <td><b>${esc(j.title)}</b>${j.salary ? `<div class="muted">${esc(j.salary)}</div>` : ""}</td>
            <td>${esc(j.company)}</td>
            <td>${esc(j.location)}${j.remote_flag ? " (remote)" : ""}</td>
            <td><span class="badge ${esc(j.source)}">${esc(j.source)}</span></td>
            <td><div class="row">
              ${j.url ? `<a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">view</a>` : ""}
              <button class="btn" data-lsave="${i}">Save</button>
            </div></td>
          </tr>`).join("")}
        </table></div>`;
      $("#j-live-saveall").onclick = () => saveLive(liveResults, null);
      $$("[data-lsave]", box).forEach((b) => b.onclick = (e) => {
        saveLive([liveResults[Number(b.dataset.lsave)]], b);
      });
    } catch (e) { st.textContent = "error: " + e.message; }
  };
  $("#j-live-go").onclick = doLiveSearch;
  $("#j-live-title").onkeydown = (e) => { if (e.key === "Enter") doLiveSearch(); };
  $("#j-live-loc").onkeydown = (e) => { if (e.key === "Enter") doLiveSearch(); };
  loadJobs();
}
async function saveLive(jobs, btn) {
  const r = await api("/api/jobs/save-live",
    {method: "POST", body: JSON.stringify({jobs})});
  if (btn) { btn.textContent = "Saved"; btn.disabled = true; }
  $("#j-live-status").innerHTML =
    `Saved <b>${r.saved}</b> new (${r.duplicates} duplicates skipped) → ` +
    `<b>${r.matches_new}</b> new matches. <a href="#" id="j-gom">View matches</a>`;
  const gom = $("#j-gom");
  if (gom) gom.onclick = (e) => { e.preventDefault(); go("matches"); };
  loadJobs();
  return r;
}
async function loadJobs() {
  const el = $("#j-list");
  el.innerHTML = `<span class="muted">Loading…</span>`;
  const jobs = await api(`/api/jobs?source=${encodeURIComponent(jobsFilter.source)}&q=${encodeURIComponent(jobsFilter.q)}&limit=100`);
  el.innerHTML = `<div class="card" style="padding:0"><table class="jobs">
    <tr><th>Title</th><th>Company</th><th>Location</th><th>Source</th><th>Posted</th><th></th></tr>
    ${jobs.map((j) => `<tr>
      <td><b>${esc(j.title)}</b>${j.salary ? `<div class="muted">${esc(j.salary)}</div>` : ""}</td>
      <td>${esc(j.company)}</td><td>${esc(j.location)}${j.remote_flag ? " (remote)" : ""}</td>
      <td><span class="badge ${esc(j.source)}">${esc(j.source)}</span></td>
      <td class="muted">${esc((j.posted_at || "").slice(0, 10))}</td>
      <td>${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">view</a>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">No jobs yet — run a collection or import a URL.</td></tr>`}
    </table></div>
    <div class="muted">Showing ${jobs.length} jobs (newest first).</div>`;
}
async function runCollection() {
  const prog = $("#j-prog");
  prog.textContent = "Collecting from enabled sources — this can take 1–3 minutes…";
  try {
    const s = await api("/api/collect", {method: "POST"});
    const lines = Object.entries(s.sources).map(([n, v]) =>
      `${n}: ${v.status}${v.new ? ` (+${v.new} new)` : ""}`);
    prog.innerHTML = `<div class="okbox">Done — ${s.jobs_new} new jobs, ${s.matches_new} new matches.<br>${lines.map(esc).join("<br>")}</div>`;
    loadJobs();
  } catch (e) { prog.innerHTML = `<div class="errbox">Collection failed: ${esc(e.message)}</div>`; }
}

/* ================= MATCHES ================= */
let matchFilter = {consultant_id: "", min_score: 0};
async function renderMatches() {
  const el = $("#tab-matches");
  el.innerHTML = `<div class="row spread"><h2>Matches</h2></div>
    <div class="card"><div class="row">
      <select id="mt-c"><option value="">All consultants</option></select>
      <label class="muted">min score</label>
      <input type="number" id="mt-s" min="0" max="100" value="${matchFilter.min_score}" style="width:70px">
      <button class="btn" id="mt-go">Filter</button></div></div>
    <div id="mt-list" class="grid"></div>`;
  const cs = await api("/api/consultants");
  $("#mt-c").innerHTML = `<option value="">All consultants</option>` +
    cs.map((c) => `<option value="${c.id}"${String(c.id) === String(matchFilter.consultant_id) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  $("#mt-go").onclick = () => {
    matchFilter.consultant_id = $("#mt-c").value;
    matchFilter.min_score = Number($("#mt-s").value) || 0;
    loadMatches();
  };
  loadMatches();
}
async function loadMatches() {
  const el = $("#mt-list");
  el.innerHTML = `<span class="muted">Loading…</span>`;
  const ms = await api(`/api/matches?consultant_id=${matchFilter.consultant_id}&min_score=${matchFilter.min_score}`);
  el.innerHTML = ms.map((m) => `
    <div class="card">
      <div class="row spread">
        <div><b>${esc(m.job_title)}</b><div class="muted">${esc(m.company)} · ${esc(m.location)}</div></div>
        <span class="badge ${esc(m.source)}">${esc(m.source)}</span>
      </div>
      <div class="row" style="margin:8px 0">
        <span class="score-num">${m.score}</span>
        <div class="scorebar"><div style="width:${Math.min(100, m.score)}%"></div></div>
        <span class="muted">for ${esc(m.consultant_name)}</span>
      </div>
      <div class="muted" title="skill ${m.score_breakdown.skill} · title ${m.score_breakdown.title} · location ${m.score_breakdown.location} · recency +${m.score_breakdown.recency}">
        skill ${m.score_breakdown.skill} · title ${m.score_breakdown.title} · location ${m.score_breakdown.location}${m.score_breakdown.recency ? " · recent +5" : ""}
      </div>
      ${m.missing_skills.length ? `<div style="margin-top:6px"><span class="muted">missing: </span>${m.missing_skills.slice(0, 12).map((s) => `<span class="chip miss">${esc(s)}</span>`).join("")}${m.missing_skills.length > 12 ? `<span class="muted">+${m.missing_skills.length - 12} more</span>` : ""}</div>` : ""}
      <div class="row" style="margin-top:10px">
        ${m.url ? `<a class="btn" href="${esc(m.url)}" target="_blank" rel="noopener">View posting</a>` : ""}
        <button class="btn" data-tailor="${m.id}">Tailor resume</button>
        <button class="btn primary" data-queue="${m.id}">Queue for apply</button>
      </div>
    </div>`).join("") || `<div class="card muted">No matches at this threshold. Run a job collection first, or lower the match threshold in Settings.</div>`;
  $$("[data-tailor]", el).forEach((b) => b.onclick = () => tailorModal(Number(b.dataset.tailor)));
  $$("[data-queue]", el).forEach((b) => b.onclick = async () => {
    await api(`/api/matches/${b.dataset.queue}/queue`, {method: "POST"});
    go("queue");
  });
}

/* ---------- tailor modal ---------- */
function diffHtml(orig, tailored) {
  const o = new Set(orig.split("\n").map((l) => l.trim()).filter(Boolean));
  const t = new Set(tailored.split("\n").map((l) => l.trim()).filter(Boolean));
  const mark = (text, other) => text.split("\n").map((l) => {
    const cls = l.trim() && !other.has(l.trim()) ? (other === o ? "added" : "removed") : "";
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join("\n");
  return {orig: mark(orig, t), tailored: mark(tailored, o)};
}
async function tailorModal(mid) {
  openModal(`<h2>Tailoring resume…</h2><div class="muted">Working…</div>`, true);
  try {
    const t = await api(`/api/matches/${mid}/tailor`, {method: "POST"});
    const full = await api(`/api/tailored/${t.id}`);
    const d = diffHtml(full.original_text || "", full.tailored_text || "");
    const flagged = t.added_skills_flagged || [];
    openModal(`
      <div class="row spread"><h2>Tailored resume</h2>
        <span class="badge">${esc(t.tailored_by === "llm" ? "AI tailored" : "keyword tailored")}</span></div>
      ${flagged.length ? `<div class="warnbox"><b>Warning — possible added skills:</b> ${flagged.map(esc).join(", ")}.
        These were detected in the tailored text but are not in the original resume.
        <label class="row" style="margin-top:6px"><input type="checkbox" id="tw-ack"> I acknowledge — these are accurate for the candidate</label></div>` : ""}
      <div class="split">
        <div><h3>Original</h3><pre class="doc">${d.orig}</pre></div>
        <div><h3>Tailored</h3><pre class="doc">${d.tailored}</pre></div>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn primary" id="tw-queue">Save &amp; queue for apply</button>
        <button class="btn" id="tw-dl">Download tailored (.txt)</button>
        <button class="btn" id="tw-close">Close</button>
      </div>`, true);
    $("#tw-close").onclick = closeModal;
    $("#tw-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = "data:text/plain;charset=utf-8," + encodeURIComponent(full.tailored_text || "");
      a.download = "tailored-resume.txt";
      a.click();
    };
    $("#tw-queue").onclick = async () => {
      if (flagged.length) {
        const ack = $("#tw-ack");
        if (!ack || !ack.checked) { alert("Please acknowledge the flagged skills first."); return; }
      }
      await api(`/api/matches/${mid}/queue`,
        {method: "POST", body: JSON.stringify({tailored_resume_id: t.id})});
      closeModal();
      go("queue");
    };
  } catch (e) {
    openModal(`<h2>Tailor</h2><div class="errbox">${esc(e.message)}</div>
      <button class="btn" onclick="document.getElementById('modal-root').innerHTML=''">Close</button>`);
  }
}

/* ================= APPLY QUEUE ================= */
async function renderQueue() {
  const el = $("#tab-queue");
  el.innerHTML = `<div class="row spread"><h2>Apply Queue</h2>
    <span class="muted">v1 is assisted apply: open the posting, submit the tailored resume, then move the card.</span></div>
    <div class="kanban" id="q-kanban"><span class="muted">Loading…</span></div>`;
  const apps = await api("/api/applications");
  const by = {};
  STATUSES.forEach((s) => by[s] = []);
  apps.forEach((a) => (by[a.status] || by.queued).push(a));
  $("#q-kanban").innerHTML = STATUSES.map((s) => `
    <div class="col"><h4>${STATUS_LABEL[s]} (${by[s].length})</h4>
      ${by[s].map((a) => `
        <div class="acard">
          <div class="t">${esc(a.job_title)}</div>
          <div class="muted">${esc(a.company)} · ${esc(a.consultant_name)} · score ${a.score}</div>
          <div class="row" style="margin-top:6px">
            ${a.url ? `<a class="btn" href="${esc(a.url)}" target="_blank" rel="noopener">Apply link</a>` : ""}
            <select data-move="${a.id}">
              ${STATUSES.map((x) => `<option value="${x}"${x === a.status ? " selected" : ""}>${STATUS_LABEL[x]}</option>`).join("")}
            </select>
          </div>
          <textarea rows="1" data-notes="${a.id}" placeholder="notes…" style="margin-top:6px">${esc(a.notes || "")}</textarea>
        </div>`).join("")}
    </div>`).join("");
  $$("[data-move]", el).forEach((sel) => sel.onchange = async () => {
    await api(`/api/applications/${sel.dataset.move}`,
      {method: "PATCH", body: JSON.stringify({status: sel.value})});
    renderQueue();
  });
  $$("[data-notes]", el).forEach((ta) => ta.onchange = async () => {
    await api(`/api/applications/${ta.dataset.notes}`,
      {method: "PATCH", body: JSON.stringify({notes: ta.value})});
  });
}

/* ================= SETTINGS ================= */
async function renderSettings() {
  const el = $("#tab-settings");
  const s = await api("/api/settings");
  const srcs = await api("/api/sources/status");
  let queries = [];
  try { queries = JSON.parse(s.search_queries || "[]"); } catch (e) {}
  let enabledSrcs = [];
  try { enabledSrcs = JSON.parse(s.enabled_sources || "[]"); } catch (e) {}

  el.innerHTML = `
    <h2>Settings</h2>
    <div class="card"><h3>Source status</h3>
      ${srcs.map((x) => {
        const dot = x.state.startsWith("ready") || x.state.startsWith("manual") ? "ok"
          : x.state.startsWith("disabled") ? "off" : "err";
        const last = x.last_run && x.last_run.at
          ? ` · last run ${esc(x.last_run.at.slice(0, 16).replace("T", " "))}: ${esc(x.last_run.status)}${x.last_run.new ? ` (+${x.last_run.new} new)` : ""}` : "";
        return `<div class="srcstat"><span class="dot ${dot}"></span>
          <b>${esc(x.label)}</b><span class="muted">${esc(x.state)}${last}</span></div>`;
      }).join("")}
      <div class="muted" style="margin-top:8px">Dice has no public API (all endpoints 404 as of Oct 2026) — Dice coverage comes from Adzuna aggregation and manual URL import.</div>
    </div>
    <div class="card"><h3>API keys</h3>
      <div class="kv">
        <label>Adzuna app id</label><input type="text" id="s-adzid" value="${esc(s.adzuna_app_id || "")}">
        <label>Adzuna app key</label><input type="password" id="s-adzkey" value="${esc(s.adzuna_app_key || "")}" placeholder="${s.adzuna_app_key ? "saved (hidden)" : ""}">
        <label>RapidAPI key (JSearch)</label><input type="password" id="s-rapid" value="${esc(s.rapidapi_key || "")}" placeholder="${s.rapidapi_key ? "saved (hidden)" : ""}">
        <label>LLM base URL</label><input type="text" id="s-llmurl" value="${esc(s.llm_base_url || "")}" placeholder="https://api.openai.com/v1">
        <label>LLM API key</label><input type="password" id="s-llmkey" value="${esc(s.llm_api_key || "")}" placeholder="${s.llm_api_key ? "saved (hidden)" : ""}">
        <label>LLM model</label><input type="text" id="s-llmmodel" value="${esc(s.llm_model || "")}" placeholder="gpt-4o-mini">
      </div>
      <div class="muted">Keys are stored on this machine only and shown masked. Without an LLM key, tailoring uses the built-in keyword method.</div>
    </div>
    <div class="card"><h3>Search queries</h3><div id="s-queries"></div>
      <button class="btn" id="s-qadd">Add query</button></div>
    <div class="card"><h3>Enabled sources</h3>
      ${srcs.filter((x) => x.name !== "urlimport").map((x) => `
        <label class="toggle"><input type="checkbox" data-src="${x.name}"${enabledSrcs.includes(x.name) ? " checked" : ""}> ${esc(x.label)}</label>`).join("")}
    </div>
    <div class="card"><h3>Match threshold</h3>
      <div class="row"><input type="range" id="s-thr" min="0" max="100" value="${esc(s.match_threshold || 60)}">
      <b id="s-thrv">${esc(s.match_threshold || 60)}</b></div>
      <div class="muted">Only matches scoring at/above this are created.</div></div>
    <div class="row"><button class="btn primary" id="s-save">Save settings</button>
      <span class="muted" id="s-msg"></span></div>`;

  const qbox = $("#s-queries");
  const qrow = (q) => {
    const d = document.createElement("div");
    d.className = "qrow";
    d.innerHTML = `<input type="text" placeholder="job title" value="${esc(q.title || "")}">
      <input type="text" placeholder="location" value="${esc(q.location || "")}">
      <button class="btn danger">x</button>`;
    $("button", d).onclick = () => d.remove();
    qbox.appendChild(d);
  };
  queries.forEach(qrow);
  $("#s-qadd").onclick = () => qrow({title: "", location: ""});
  $("#s-thr").oninput = (e) => $("#s-thrv").textContent = e.target.value;
  $("#s-save").onclick = async () => {
    const qs = $$("#s-queries .qrow").map((d) => ({
      title: $("input", d).value.trim(), location: $$("input", d)[1].value.trim(),
    })).filter((q) => q.title);
    const payload = {
      adzuna_app_id: $("#s-adzid").value.trim(),
      adzuna_app_key: $("#s-adzkey").value,
      rapidapi_key: $("#s-rapid").value,
      llm_base_url: $("#s-llmurl").value.trim(),
      llm_api_key: $("#s-llmkey").value,
      llm_model: $("#s-llmmodel").value.trim(),
      search_queries: qs,
      enabled_sources: $$("[data-src]").filter((c) => c.checked).map((c) => c.dataset.src),
      match_threshold: $("#s-thr").value,
    };
    // don't overwrite saved keys with the masked echo
    for (const k of ["adzuna_app_key", "rapidapi_key", "llm_api_key"])
      if (payload[k].includes("***")) delete payload[k];
    await api("/api/settings", {method: "PUT", body: JSON.stringify(payload)});
    $("#s-msg").textContent = "saved";
    setTimeout(() => $("#s-msg").textContent = "", 2000);
    renderSettings();
  };
}

/* ---------- router ---------- */
function render(tab) {
  ({consultants: renderConsultants, jobs: renderJobs, matches: renderMatches,
    queue: renderQueue, settings: renderSettings})[tab]();
}
render("consultants");
