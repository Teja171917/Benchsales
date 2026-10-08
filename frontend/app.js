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

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/* ---------- theme ---------- */
function initTheme() {
  const btn = $("#theme-toggle");
  const sync = () => {
    btn.textContent = (document.documentElement.getAttribute("data-theme") === "dark") ? "☀️" : "🌙";
  };
  btn.onclick = () => {
    const next = (document.documentElement.getAttribute("data-theme") === "dark") ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("bp-theme", next); } catch (e) {}
    sync();
  };
  sync();
}

/* ---------- toasts ---------- */
function toast(msg, kind) {
  const box = $("#toasts");
  const d = document.createElement("div");
  d.className = "toast" + (kind ? " " + kind : "");
  d.textContent = msg;
  box.appendChild(d);
  setTimeout(() => {
    d.style.transition = "opacity .3s"; d.style.opacity = "0";
    setTimeout(() => d.remove(), 320);
  }, 3400);
}

/* ---------- drawer ---------- */
let drawerReturnFocus = null;
function openDrawer(html) {
  drawerReturnFocus = document.activeElement;
  const root = $("#drawer-root");
  root.innerHTML = `<div class="drawer-back"></div><aside class="drawer" role="dialog" aria-modal="true">${html}</aside>`;
  $(".drawer-back", root).addEventListener("click", closeDrawer);
  const c = $(".drawer-close", root);
  if (c) { c.onclick = closeDrawer; c.focus(); }
}
function closeDrawer() {
  $("#drawer-root").innerHTML = "";
  if (drawerReturnFocus && drawerReturnFocus.focus) drawerReturnFocus.focus();
}

/* ---------- nav badges ---------- */
async function refreshBadges() {
  try {
    const [jobs, matches, apps, briefing] = await Promise.all([
      api("/api/jobs?limit=500"), api("/api/matches?min_score=0"), api("/api/applications"),
      api("/api/office/briefing").catch(() => null),
    ]);
    const set = (id, n) => { const b = $(id); if (b) b.textContent = n > 0 ? String(n) : ""; };
    set("#nb-jobs", jobs.length);
    set("#nb-matches", matches.length);
    set("#nb-queue", apps.filter((a) => !["rejected", "withdrawn"].includes(a.status)).length);
    if (briefing && briefing.agents) {
      const attn = (briefing.agents.watchdog?.stale || 0) + (briefing.agents.tailor?.drafted || 0);
      set("#nb-office", attn);
    }
  } catch (e) { /* badges are best-effort */ }
}

/* ---------- skeletons ---------- */
const skelCards = (n) => Array.from({length: n}, () =>
  `<div class="card"><div class="skel" style="height:20px;width:60%;margin-bottom:10px">&nbsp;</div>
   <div class="skel" style="height:13px;width:90%;margin-bottom:6px">&nbsp;</div>
   <div class="skel" style="height:13px;width:75%">&nbsp;</div></div>`).join("");
const skelRows = (n) => Array.from({length: n}, () =>
  `<div class="skel" style="height:44px;margin-bottom:8px">&nbsp;</div>`).join("");

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
let modalReturnFocus = null;
function openModal(html, wide) {
  modalReturnFocus = document.activeElement;
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-back"><div class="modal${wide ? " wide" : ""}" role="dialog" aria-modal="true">${html}</div></div>`;
  $(".modal-back", root).addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-back")) closeModal();
  });
  const m = $(".modal", root);
  m.addEventListener("keydown", trapTab);
  const f = m.querySelector("button, input, select, textarea, a[href]");
  if (f) f.focus();
}
function trapTab(e) {
  if (e.key !== "Tab") return;
  const items = Array.from(e.currentTarget.querySelectorAll("button, input, select, textarea, a[href]"))
    .filter((x) => !x.disabled && x.offsetParent !== null);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
function closeModal() {
  $("#modal-root").innerHTML = "";
  if (modalReturnFocus && modalReturnFocus.focus) modalReturnFocus.focus();
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if ($("#drawer-root").firstChild) closeDrawer();
    else if ($("#modal-root").firstChild) closeModal();
  }
});

/* ================= CONSULTANTS ================= */
async function renderConsultants() {
  const el = $("#tab-consultants");
  el.innerHTML = `<div class="row spread"><h2>Consultants</h2>
    <button class="btn primary" id="c-add">Add consultant</button></div>
    <div id="c-list" class="grid">${skelCards(3)}</div>`;
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
    toast("Consultant removed", "ok");
    refreshBadges();
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
      toast(`Resume parsed — ${d.skills.length} skills`, "ok");
      refreshBadges();
      renderConsultants();
    } catch (e) { msg.textContent = "error: " + e.message; toast("Upload failed: " + e.message, "err"); }
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
    toast(c.id ? "Consultant updated" : "Consultant added", "ok");
    refreshBadges();
    renderConsultants();
  };
}

/* ---------- job drawer ---------- */
function jobDrawerHtml(j, opts) {
  opts = opts || {};
  return `
    <button class="drawer-close" aria-label="Close">✕</button>
    <div class="row" style="gap:8px;margin-bottom:10px">
      <span class="badge ${esc(j.source || "")}">${esc(j.source || "job")}</span>
      ${j.remote_flag ? `<span class="badge">remote</span>` : ""}</div>
    <h2>${esc(j.title)}</h2>
    <div class="muted" style="margin-bottom:10px">${esc(j.company)}${j.location ? " · " + esc(j.location) : ""}</div>
    <div class="row" style="gap:14px;margin-bottom:6px">
      ${j.salary ? `<span><b>${esc(j.salary)}</b></span>` : ""}
      <span class="muted" title="${esc(j.posted_at || "")}">posted ${j.posted_at ? esc(ago(j.posted_at)) : "unknown"}</span>
      ${j.employment_type ? `<span class="muted">${esc(j.employment_type)}</span>` : ""}
    </div>
    ${j.description ? `<h3 style="margin-top:14px">Description</h3><div class="desc">${esc(j.description)}</div>`
      : `<div class="muted" style="margin:12px 0">No description captured.</div>`}
    <div class="row" style="margin:12px 0">
      ${j.url ? `<a class="btn primary" href="${esc(j.url)}" target="_blank" rel="noopener">View posting</a>` : ""}
      ${opts.unsaved ? `<button class="btn" id="dr-save">Save to job board</button>` : ""}
    </div>
    <div id="dr-matches"><span class="muted">Loading matched consultants…</span></div>`;
}
async function openJobDrawer(job, opts) {
  opts = opts || {};
  openDrawer(jobDrawerHtml(job, opts));
  const box = $("#dr-matches");
  const sv = $("#dr-save");
  if (sv) sv.onclick = async () => {
    try {
      const r = await api("/api/jobs/save-live", {method: "POST", body: JSON.stringify({jobs: [job]})});
      toast(`Saved (${r.saved} new)`, "ok"); refreshBadges(); closeDrawer();
      if ($("#j-list")) loadJobs();
    } catch (e) { toast("Save failed: " + e.message, "err"); }
  };
  if (opts.unsaved || !job.id) { if (box) box.innerHTML = ""; return; }
  try {
    const ms = await api("/api/matches?min_score=0");
    const mine = ms.filter((m) => m.job_id === job.id).slice(0, 8);
    box.innerHTML = `<h3>Matched consultants (${mine.length})</h3>` + (mine.map((m) => `
      <div class="mrow"><div style="flex:1"><b>${esc(m.consultant_name)}</b>
        <div class="muted">score ${m.score}</div></div>
        <button class="btn" data-drq="${m.id}">Queue</button></div>`).join("")
      || `<div class="muted">No consultant matches this job yet.</div>`);
    $$("#dr-matches [data-drq]").forEach((b) => b.onclick = async () => {
      await api(`/api/matches/${b.dataset.drq}/queue`, {method: "POST"});
      toast("Queued for apply", "ok"); refreshBadges(); closeDrawer(); go("queue");
    });
  } catch (e) { box.innerHTML = `<div class="muted">Couldn't load matches.</div>`; }
}

/* ================= JOBS ================= */
let jobsFilter = {source: "", q: "", remote: false, location: "", emptype: "", posted: "", sort: "newest"};
let jobsCache = [];
async function renderJobs() {
  const el = $("#tab-jobs");
  el.innerHTML = `
    <div class="row spread"><h2>Jobs</h2>
      <button class="btn primary" id="j-run">Run job collection</button></div>
    <div class="muted" id="j-fresh" style="margin:-4px 0 10px"></div>
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
    <div class="card"><div class="row spread" style="margin-bottom:12px"><h3 style="margin:0">Job board</h3>
      <button class="btn" id="j-reset">Reset filters</button></div>
      <div class="filters">
        <div><label class="flabel" for="j-q">Keyword</label>
          <input type="text" id="j-q" placeholder="title, company, skills…" value="${esc(jobsFilter.q)}"></div>
        <div><label class="flabel" for="j-source">Source</label>
          <select id="j-source"><option value="">All sources</option></select></div>
        <div><label class="flabel" for="j-loc">Location</label>
          <input type="text" id="j-loc" placeholder="city, state…" value="${esc(jobsFilter.location)}"></div>
        <div><label class="flabel" for="j-emp">Employment type</label>
          <select id="j-emp"><option value="">Any type</option></select></div>
        <div><label class="flabel" for="j-posted">Posted</label>
          <select id="j-posted">
            <option value="">Any time</option>
            <option value="1"${jobsFilter.posted === "1" ? " selected" : ""}>Last 24 hours</option>
            <option value="7"${jobsFilter.posted === "7" ? " selected" : ""}>Last 7 days</option>
            <option value="30"${jobsFilter.posted === "30" ? " selected" : ""}>Last 30 days</option>
          </select></div>
        <div><label class="flabel" for="j-sort">Sort by</label>
          <select id="j-sort">
            <option value="newest"${jobsFilter.sort === "newest" ? " selected" : ""}>Newest first</option>
            <option value="oldest"${jobsFilter.sort === "oldest" ? " selected" : ""}>Oldest first</option>
            <option value="title"${jobsFilter.sort === "title" ? " selected" : ""}>Title A–Z</option>
            <option value="company"${jobsFilter.sort === "company" ? " selected" : ""}>Company A–Z</option>
          </select></div>
        <div><span class="flabel">Options</span>
          <label class="fcheck"><input type="checkbox" id="j-remote"${jobsFilter.remote ? " checked" : ""}> Remote only</label></div>
      </div></div>
    <div id="j-count" class="muted" style="margin:0 2px 8px"></div>
    <div id="j-list">${skelRows(8)}</div>`;
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
      toast(j.duplicate ? "Duplicate skipped" : `Imported: ${j.title}`, j.duplicate ? "" : "ok");
      refreshBadges();
      loadJobs();
    } catch (e) { msg.textContent = "error: " + e.message; toast("Import failed: " + e.message, "err"); }
  };
  let jDeb = null;
  const jLive = (fn) => (e) => { clearTimeout(jDeb); jDeb = setTimeout(() => fn(e.target.value), 250); };
  $("#j-q").addEventListener("input", jLive((v) => { jobsFilter.q = v; applyJobFilters(); }));
  $("#j-loc").addEventListener("input", jLive((v) => { jobsFilter.location = v; applyJobFilters(); }));
  $("#j-source").onchange = (e) => { jobsFilter.source = e.target.value; applyJobFilters(); };
  $("#j-emp").onchange = (e) => { jobsFilter.emptype = e.target.value; applyJobFilters(); };
  $("#j-posted").onchange = (e) => { jobsFilter.posted = e.target.value; applyJobFilters(); };
  $("#j-sort").onchange = (e) => { jobsFilter.sort = e.target.value; applyJobFilters(); };
  $("#j-remote").onchange = (e) => { jobsFilter.remote = e.target.checked; applyJobFilters(); };
  $("#j-reset").onclick = () => {
    jobsFilter = {source: "", q: "", remote: false, location: "", emptype: "", posted: "", sort: "newest"};
    $("#j-q").value = ""; $("#j-loc").value = "";
    $("#j-source").value = ""; $("#j-emp").value = "";
    $("#j-posted").value = ""; $("#j-sort").value = "newest";
    $("#j-remote").checked = false;
    applyJobFilters();
  };
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
          ${liveResults.map((j, i) => `<tr data-liveidx="${i}">
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
  $("#j-live-results").addEventListener("click", (e) => {
    if (e.target.closest("a, button")) return;
    const tr = e.target.closest("tr[data-liveidx]");
    if (!tr) return;
    openJobDrawer(liveResults[Number(tr.dataset.liveidx)], {unsaved: true});
  });
  $("#j-list").addEventListener("click", (e) => {
    if (e.target.closest("a, button")) return;
    const tr = e.target.closest("tr[data-jobid]");
    if (!tr) return;
    const j = jobsCache.find((x) => String(x.id) === tr.dataset.jobid);
    if (j) openJobDrawer(j);
  });
  updateFreshness();
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
  if (!el) return;
  el.innerHTML = skelRows(8);
  jobsCache = await api("/api/jobs?limit=500");
  const srcs = await api("/api/sources/status");
  $("#j-source").innerHTML = `<option value="">All sources</option>` +
    srcs.filter((s) => s.name !== "urlimport")
      .map((s) => `<option value="${s.name}"${jobsFilter.source === s.name ? " selected" : ""}>${esc(s.label)}</option>`).join("");
  const types = [...new Set(jobsCache.map((j) => (j.employment_type || "").trim()).filter(Boolean))].sort();
  $("#j-emp").innerHTML = `<option value="">Any type</option>` +
    types.map((t) => `<option${jobsFilter.emptype === t ? " selected" : ""}>${esc(t)}</option>`).join("");
  applyJobFilters();
}
function jobMatches(j) {
  const f = jobsFilter;
  if (f.source && j.source !== f.source) return false;
  if (f.remote && !j.remote_flag) return false;
  if (f.emptype && (j.employment_type || "").trim() !== f.emptype) return false;
  if (f.location && !(j.location || "").toLowerCase().includes(f.location.toLowerCase())) return false;
  if (f.posted) {
    if (!j.posted_at) return false;
    const d = new Date(j.posted_at);
    if (isNaN(d.getTime())) return false;
    if (Date.now() - d.getTime() > Number(f.posted) * 864e5) return false;
  }
  if (f.q) {
    const hay = `${j.title || ""} ${j.company || ""} ${j.description || ""}`.toLowerCase();
    if (!f.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  }
  return true;
}
function applyJobFilters() {
  const list = jobsCache.filter(jobMatches);
  const ts = (j) => { const d = new Date(j.posted_at || 0); return isNaN(d.getTime()) ? 0 : d.getTime(); };
  const s = jobsFilter.sort;
  list.sort((a, b) => s === "title" ? (a.title || "").localeCompare(b.title || "")
    : s === "company" ? (a.company || "").localeCompare(b.company || "")
    : s === "oldest" ? ts(a) - ts(b) : ts(b) - ts(a));
  const cnt = $("#j-count");
  if (cnt) cnt.textContent = `Showing ${list.length} of ${jobsCache.length} jobs`;
  $("#j-list").innerHTML = `<div class="card" style="padding:0"><table class="jobs">
    <tr><th>Title</th><th>Company</th><th>Location</th><th>Source</th><th>Posted</th><th></th></tr>
    ${list.map((j) => `<tr data-jobid="${j.id}">
      <td><b>${esc(j.title)}</b>${j.salary ? `<div class="muted">${esc(j.salary)}</div>` : ""}</td>
      <td>${esc(j.company)}</td><td>${esc(j.location)}${j.remote_flag ? " (remote)" : ""}</td>
      <td><span class="badge ${esc(j.source)}">${esc(j.source)}</span></td>
      <td class="muted" title="${esc((j.posted_at || "").slice(0, 10))}">${j.posted_at ? esc(ago(j.posted_at)) : "—"}</td>
      <td>${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">view</a>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">No jobs match these filters.</td></tr>`}
    </table></div>`;
}
async function updateFreshness() {
  const f = $("#j-fresh");
  if (!f) return;
  try {
    const st = await api("/api/collect/status");
    if (st.running) {
      f.textContent = "Collection running right now…";
      return;
    }
    const last = st.last_result
      ? ` (+${st.last_result.jobs_new} new jobs, +${st.last_result.matches_new} new matches)` : "";
    if (st.interval_minutes > 0) {
      f.textContent = `Auto-refresh every ${st.interval_minutes} min · last run ${ago(st.last_run_at)}${last}`;
    } else {
      f.textContent = st.last_run_at
        ? `Auto-refresh is off · last run ${ago(st.last_run_at)}${last} — click "Run job collection" for fresh data`
        : `Auto-refresh is off — click "Run job collection" to pull fresh jobs`;
    }
  } catch (e) { f.textContent = ""; }
}
async function runCollection() {
  const prog = $("#j-prog");
  if (prog) prog.textContent = "Collecting from enabled sources — this can take 1–3 minutes…";
  else toast("Collecting from enabled sources — this can take 1–3 minutes…");
  try {
    const s = await api("/api/collect", {method: "POST"});
    const lines = Object.entries(s.sources).map(([n, v]) =>
      `${n}: ${v.status}${v.new ? ` (+${v.new} new)` : ""}`);
    if (prog) prog.innerHTML = `<div class="okbox">Done — ${s.jobs_new} new jobs, ${s.matches_new} new matches.<br>${lines.map(esc).join("<br>")}</div>`;
    else toast(`Done — ${s.jobs_new} new jobs, ${s.matches_new} new matches`, "ok");
    if ($("#j-list")) loadJobs();
    if ($("#j-fresh")) updateFreshness();
    refreshBadges();
  } catch (e) {
    if (prog) prog.innerHTML = `<div class="errbox">Collection failed: ${esc(e.message)}</div>`;
    else toast("Collection failed: " + e.message, "err");
  }
}

/* ================= MATCHES ================= */
let matchFilter = {consultant_id: "", min_score: 0, source: "", sort: "best"};
async function renderMatches() {
  const el = $("#tab-matches");
  el.innerHTML = `<div class="row spread"><h2>Matches</h2></div>
    <div class="card"><div class="filters">
      <div><label class="flabel" for="mt-c">Consultant</label>
        <select id="mt-c"><option value="">All consultants</option></select></div>
      <div><label class="flabel" for="mt-s">Min score</label>
        <input type="number" id="mt-s" min="0" max="100" value="${matchFilter.min_score}"></div>
      <div><label class="flabel" for="mt-src">Source</label>
        <select id="mt-src"><option value="">All sources</option></select></div>
      <div><label class="flabel" for="mt-sort">Sort by</label>
        <select id="mt-sort">
          <option value="best"${matchFilter.sort === "best" ? " selected" : ""}>Best score first</option>
          <option value="low"${matchFilter.sort === "low" ? " selected" : ""}>Lowest score first</option>
        </select></div>
      <div><span class="flabel">&nbsp;</span>
        <button class="btn primary" id="mt-go">Apply filters</button></div>
    </div></div>
    <div id="mt-count" class="muted" style="margin:0 2px 8px"></div>
    <div id="mt-list" class="grid"></div>`;
  const cs = await api("/api/consultants");
  $("#mt-c").innerHTML = `<option value="">All consultants</option>` +
    cs.map((c) => `<option value="${c.id}"${String(c.id) === String(matchFilter.consultant_id) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  const srcs = await api("/api/sources/status");
  $("#mt-src").innerHTML = `<option value="">All sources</option>` +
    srcs.filter((s) => s.name !== "urlimport")
      .map((s) => `<option value="${s.name}"${matchFilter.source === s.name ? " selected" : ""}>${esc(s.label)}</option>`).join("");
  $("#mt-go").onclick = () => {
    matchFilter.consultant_id = $("#mt-c").value;
    matchFilter.min_score = Number($("#mt-s").value) || 0;
    matchFilter.source = $("#mt-src").value;
    matchFilter.sort = $("#mt-sort").value;
    loadMatches();
  };
  loadMatches();
}
async function loadMatches() {
  const el = $("#mt-list");
  el.innerHTML = skelCards(6);
  let ms = await api(`/api/matches?consultant_id=${matchFilter.consultant_id}&min_score=${matchFilter.min_score}`);
  if (matchFilter.source) ms = ms.filter((m) => m.source === matchFilter.source);
  ms.sort((a, b) => matchFilter.sort === "low" ? a.score - b.score : b.score - a.score);
  const cnt = $("#mt-count");
  if (cnt) cnt.textContent = `${ms.length} matches`;
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
      <div class="sbreak">${(() => {
        const b = m.score_breakdown || {};
        const bar = (l, v) => { const n = Number(v) || 0; return `
          <div class="sb"><div class="sl">${l}</div><div class="sbar"><div style="width:${Math.min(100, n)}%"></div></div>
          <div class="sv">${v == null ? "—" : v}</div></div>`; };
        return bar("skill", b.skill) + bar("title", b.title) + bar("location", b.location)
          + (b.recency ? `<div class="sb"><div class="sl">recency</div><div class="sv">+${b.recency}</div></div>` : "");
      })()}</div>
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
    toast("Queued for apply", "ok");
    refreshBadges();
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
        if (!ack || !ack.checked) { toast("Please acknowledge the flagged skills first.", "err"); return; }
      }
      await api(`/api/matches/${mid}/queue`,
        {method: "POST", body: JSON.stringify({tailored_resume_id: t.id})});
      closeModal();
      toast("Saved & queued for apply", "ok");
      refreshBadges();
      go("queue");
    };
  } catch (e) {
    openModal(`<h2>Tailor</h2><div class="errbox">${esc(e.message)}</div>
      <button class="btn" onclick="document.getElementById('modal-root').innerHTML=''">Close</button>`);
  }
}

/* ================= APPLY QUEUE ================= */
let queueFilter = {consultant: ""};
async function renderQueue() {
  const el = $("#tab-queue");
  el.innerHTML = `<div class="row spread"><h2>Apply Queue</h2>
    <span class="muted">v1 is assisted apply: open the posting, submit the tailored resume, then move the card.</span></div>
    <div class="card"><div class="filters" style="grid-template-columns:repeat(auto-fit,minmax(200px,260px))">
      <div><label class="flabel" for="q-c">Consultant</label>
        <select id="q-c"><option value="">All consultants</option></select></div>
    </div></div>
    <div id="q-count" class="muted" style="margin:0 2px 8px"></div>
    <div class="kanban" id="q-kanban">${skelCards(4)}</div>`;
  const apps = await api("/api/applications");
  const names = [...new Set(apps.map((a) => a.consultant_name).filter(Boolean))].sort();
  $("#q-c").innerHTML = `<option value="">All consultants</option>` +
    names.map((n) => `<option${queueFilter.consultant === n ? " selected" : ""}>${esc(n)}</option>`).join("");
  $("#q-c").onchange = (e) => { queueFilter.consultant = e.target.value; drawQueue(); };
  const drawQueue = () => {
    const list = queueFilter.consultant
      ? apps.filter((a) => a.consultant_name === queueFilter.consultant) : apps;
    const by = {};
    STATUSES.forEach((s) => by[s] = []);
    list.forEach((a) => (by[a.status] || by.queued).push(a));
    $("#q-count").textContent = `${list.length} applications`;
    $("#q-kanban").innerHTML = STATUSES.map((s) => `
    <div class="col" data-status="${s}"><h4>${STATUS_LABEL[s]} (${by[s].length})</h4>
      ${by[s].map((a) => `
        <div class="acard" draggable="true" data-appid="${a.id}">
          <div class="t">${esc(a.job_title)}</div>
          <div class="muted">${esc(a.company)} · ${esc(a.consultant_name)} · score ${a.score}</div>
          <div class="row" style="margin-top:6px">
            ${a.url ? `<a class="btn" href="${esc(a.url)}" target="_blank" rel="noopener">Apply link</a>` : ""}
            <select data-move="${a.id}" aria-label="Move to status">
              ${STATUSES.map((x) => `<option value="${x}"${x === a.status ? " selected" : ""}>${STATUS_LABEL[x]}</option>`).join("")}
            </select>
          </div>
          <textarea rows="1" data-notes="${a.id}" placeholder="notes…" style="margin-top:6px">${esc(a.notes || "")}</textarea>
        </div>`).join("")}
    </div>`).join("");
    const kanban = $("#q-kanban");
    $$(".acard", kanban).forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", card.dataset.appid);
        e.dataTransfer.effectAllowed = "move";
        setTimeout(() => card.classList.add("dragging"), 0);
      });
      card.addEventListener("dragend", () => card.classList.remove("dragging"));
    });
    $$(".col", kanban).forEach((col) => {
      col.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("dragover"); });
      col.addEventListener("dragleave", () => col.classList.remove("dragover"));
      col.addEventListener("drop", async (e) => {
        e.preventDefault(); col.classList.remove("dragover");
        const aid = e.dataTransfer.getData("text/plain");
        const status = col.dataset.status;
        if (!aid || !status) return;
        await api(`/api/applications/${aid}`, {method: "PATCH", body: JSON.stringify({status})});
        toast(`Moved to ${STATUS_LABEL[status]}`, "ok");
        refreshBadges();
        renderQueue();
      });
    });
    $$("[data-move]", el).forEach((sel) => sel.onchange = async () => {
      await api(`/api/applications/${sel.dataset.move}`,
        {method: "PATCH", body: JSON.stringify({status: sel.value})});
      toast(`Moved to ${STATUS_LABEL[sel.value]}`, "ok");
      refreshBadges();
      renderQueue();
    });
    $$("[data-notes]", el).forEach((ta) => ta.onchange = async () => {
      await api(`/api/applications/${ta.dataset.notes}`,
        {method: "PATCH", body: JSON.stringify({notes: ta.value})});
    });
  };
  drawQueue();
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
    <div class="card"><h3>Auto-refresh</h3>
      <div class="kv">
        <label>Re-pull jobs every</label>
        <select id="s-interval">
          <option value="0"${s.collect_interval_minutes === "0" ? " selected" : ""}>Off — manual only</option>
          <option value="15"${s.collect_interval_minutes === "15" ? " selected" : ""}>15 minutes</option>
          <option value="30"${s.collect_interval_minutes === "30" ? " selected" : ""}>30 minutes</option>
          <option value="60"${!s.collect_interval_minutes || s.collect_interval_minutes === "60" ? " selected" : ""}>1 hour (recommended)</option>
          <option value="120"${s.collect_interval_minutes === "120" ? " selected" : ""}>2 hours</option>
          <option value="360"${s.collect_interval_minutes === "360" ? " selected" : ""}>6 hours</option>
        </select>
      </div>
      <div class="muted">BenchPilot re-pulls every enabled source on this schedule and re-matches consultants automatically — new postings land in the job board on their own. With Adzuna keys, keep 1 hour or slower (free tier allows 250 calls/day).</div>
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
      collect_interval_minutes: $("#s-interval").value,
    };
    // don't overwrite saved keys with the masked echo
    for (const k of ["adzuna_app_key", "rapidapi_key", "llm_api_key"])
      if (payload[k].includes("***")) delete payload[k];
    await api("/api/settings", {method: "PUT", body: JSON.stringify(payload)});
    toast("Settings saved", "ok");
    renderSettings();
  };
}

/* ================= OVERVIEW ================= */
async function renderOverview() {
  const el = $("#tab-overview");
  el.innerHTML = `
    <div class="row spread"><h2>Overview</h2>
      <button class="btn" id="ov-refresh">Refresh</button></div>
    <div class="stats" id="ov-stats">${skelCards(4)}</div>
    <div class="dash-grid">
      <div class="card"><h3>Pipeline</h3><div class="funnel" id="ov-funnel">${skelRows(5)}</div></div>
      <div class="card"><h3>Data freshness</h3><div id="ov-fresh" class="muted">Loading…</div>
        <div style="margin-top:12px"><button class="btn" id="ov-collect">Run job collection</button></div></div>
    </div>
    <div class="card"><div class="row spread"><h3 style="margin:0">Top matches</h3>
      <button class="btn" id="ov-allm">View all</button></div>
      <div id="ov-top" style="margin-top:6px">${skelRows(3)}</div></div>
    <div class="card" id="ov-attn-card" style="display:none"><h3>Needs attention</h3><div id="ov-attn"></div></div>`;
  $("#ov-refresh").onclick = () => { renderOverview(); refreshBadges(); };
  $("#ov-allm").onclick = () => go("matches");
  $("#ov-collect").onclick = async () => { await runCollection(); renderOverview(); refreshBadges(); };
  try {
    const [cs, jobs, ms, apps, st] = await Promise.all([
      api("/api/consultants"), api("/api/jobs?limit=500"),
      api("/api/matches?min_score=0"), api("/api/applications"),
      api("/api/collect/status").catch(() => null),
    ]);
    const placed = apps.filter((a) => a.status === "placed").length;
    const active = apps.filter((a) => !["rejected", "withdrawn", "placed"].includes(a.status)).length;
    const noResume = cs.filter((c) => !c.has_resume);
    $("#ov-stats").innerHTML = [
      ["Consultants", cs.length, "", "consultants"],
      ["Jobs collected", jobs.length, "accent", "jobs"],
      ["Matches", ms.length, "accent", "matches"],
      ["Active applications", active, "", "queue"],
      ["Placed", placed, "good", "queue"],
    ].map(([l, n, cls, tab]) => `<div class="stat ${cls}" data-goto="${tab}" role="button" tabindex="0">
        <div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
    $$("#ov-stats .stat").forEach((s) => {
      s.onclick = () => go(s.dataset.goto);
      s.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") go(s.dataset.goto); };
    });
    const counts = STATUSES.map((s) => apps.filter((a) => a.status === s).length);
    const max = Math.max(1, ...counts);
    $("#ov-funnel").innerHTML = STATUSES.map((s, i) => `
      <div class="frow"><span class="fl">${STATUS_LABEL[s]}</span>
        <div class="fbar"><div style="width:${Math.round((counts[i] / max) * 100)}%"></div></div>
        <span class="fn">${counts[i]}</span></div>`).join("");
    const f = $("#ov-fresh");
    if (st) {
      const last = st.last_result
        ? ` (+${st.last_result.jobs_new} new jobs, +${st.last_result.matches_new} new matches)` : "";
      f.textContent = st.running ? "Collection running right now…"
        : st.interval_minutes > 0
          ? `Auto-refresh every ${st.interval_minutes} min · last run ${ago(st.last_run_at)}${last}`
          : (st.last_run_at ? `Auto-refresh off · last run ${ago(st.last_run_at)}${last}` : "Auto-refresh off — no runs yet");
    } else f.textContent = "Status unavailable";
    const top = ms.slice(0, 5);
    $("#ov-top").innerHTML = top.map((m) => `
      <div class="topmatch"><div class="ti"><div class="tt">${esc(m.job_title)}</div>
        <div class="muted">${esc(m.company)} · ${esc(m.consultant_name)}</div></div>
        <span class="score-num">${m.score}</span>
        <button class="btn primary" data-ovq="${m.id}">Queue</button></div>`).join("")
      || `<div class="muted">No matches yet — run a job collection.</div>`;
    $$("#ov-top [data-ovq]").forEach((b) => b.onclick = async () => {
      await api(`/api/matches/${b.dataset.ovq}/queue`, {method: "POST"});
      toast("Queued for apply", "ok"); refreshBadges(); renderOverview();
    });
    if (noResume.length) {
      $("#ov-attn-card").style.display = "";
      $("#ov-attn").innerHTML = `<div class="warnbox">${noResume.length} consultant${noResume.length > 1 ? "s" : ""} without a resume: ${noResume.map((c) => esc(c.name)).join(", ")}. <a href="#" id="ov-goc">Upload now</a></div>`;
      $("#ov-goc").onclick = (e) => { e.preventDefault(); go("consultants"); };
    }
  } catch (e) {
    el.innerHTML = `<div class="errbox">Couldn't load overview: ${esc(e.message)}</div>`;
  }
  refreshBadges();
}

/* ================= AGENT OFFICE ================= */
const AGENT_INFO = {
  scout: {name: "Scout", desc: "Watches the board for fresh matches above your threshold, grouped per consultant."},
  tailor: {name: "Tailor", desc: "Pre-drafts tailored resumes for top matches (score 85+). Drafts only — flagged skills need your review before anything is queued."},
  watchdog: {name: "Watchdog", desc: "Flags pipeline going cold: queued items with no action, applications with no update."},
};
async function renderOffice() {
  const el = $("#tab-office");
  el.innerHTML = `
    <div class="row spread"><div><h2 style="margin-bottom:2px">Agent Office</h2>
      <div class="muted">Three agents working your pipeline around the clock — runs automatically every day.</div></div>
      <button class="btn primary" id="of-run">Run the office now</button></div>
    <div class="stats" id="of-stats" style="margin-top:14px">${skelCards(4)}</div>
    <div class="dash-grid" id="of-agents">${skelCards(3)}</div>
    <div id="of-briefing">${skelRows(4)}</div>`;
  $("#of-run").onclick = async () => {
    const b = $("#of-run");
    b.disabled = true; b.textContent = "Office is working…";
    try {
      await api("/api/office/run", {method: "POST"});
      toast("Office run complete — briefing refreshed", "ok");
    } catch (e) { toast("Office run failed: " + e.message, "err"); }
    renderOffice(); refreshBadges();
  };
  let br;
  try { br = await api("/api/office/briefing"); }
  catch (e) {
    $("#of-briefing").innerHTML = `<div class="errbox">Couldn't load the briefing: ${esc(e.message)}</div>`;
    $("#of-stats").innerHTML = ""; $("#of-agents").innerHTML = "";
    return;
  }
  if (!br.run_at) {
    $("#of-stats").innerHTML = ""; $("#of-agents").innerHTML = "";
    $("#of-briefing").innerHTML = `<div class="card"><h3>The office hasn't run yet</h3>
      <div class="muted" style="margin-bottom:10px">It runs automatically once a day. Run it now for your first briefing: new matches, drafted resumes, and stale pipeline items.</div>
      <button class="btn primary" id="of-run2">Run the office now</button></div>`;
    $("#of-run2").onclick = () => $("#of-run").click();
    return;
  }
  const A = br.agents || {};
  const scout = A.scout || {new_matches: 0, by_consultant: {}};
  const tailor = A.tailor || {drafted: 0, drafts: []};
  const wd = A.watchdog || {stale: 0, items: []};

  $("#of-stats").innerHTML = [
    ["New matches (24h)", scout.new_matches, "accent", "matches"],
    ["Resume drafts ready", tailor.drafted, tailor.drafted ? "good" : "", null],
    ["Stale pipeline items", wd.stale, wd.stale ? "accent" : "", "queue"],
    ["Briefing from", ago(br.run_at), "", null],
  ].map(([l, n, cls, tab]) => `<div class="stat ${cls}"${tab ? ` data-goto="${tab}" role="button" tabindex="0"` : ""}>
      <div class="n">${esc(String(n))}</div><div class="l">${l}</div></div>`).join("");
  $$("#of-stats .stat[data-goto]").forEach((s) => {
    s.onclick = () => go(s.dataset.goto);
    s.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") go(s.dataset.goto); };
  });

  $("#of-agents").innerHTML = ["scout", "tailor", "watchdog"].map((k) => {
    const info = AGENT_INFO[k];
    const res = k === "scout" ? `${scout.new_matches} new matches`
      : k === "tailor" ? `${tailor.drafted} drafts ready`
      : `${wd.stale} items flagged`;
    return `<div class="card"><h3>${info.name}</h3>
      <div class="muted" style="margin-bottom:8px">${info.desc}</div>
      <div><b>${esc(res)}</b> <span class="muted">· last run ${esc(ago(br.run_at))}</span></div></div>`;
  }).join("");

  const secs = [];
  const consultants = Object.keys(scout.by_consultant || {});
  secs.push(`<div class="card"><div class="row spread"><h3 style="margin:0">New matches in the last 24 hours</h3>
    ${consultants.length ? `<button class="btn" id="of-allm">Open matches</button>` : ""}</div>
    ${consultants.length ? consultants.map((c) => `
      <div style="margin-top:10px"><b>${esc(c)}</b>
        ${(scout.by_consultant[c] || []).map((m) => `
          <div class="row" style="margin-top:6px">
            <span class="score-num" style="font-size:14px">${m.score}</span>
            <div><b>${esc(m.job_title)}</b>
              <span class="muted"> · ${esc(m.company)} · ${esc(m.location)}</span></div>
            <span class="badge ${esc(m.source)}">${esc(m.source)}</span>
          </div>`).join("")}</div>`).join("")
      : `<div class="muted" style="margin-top:8px">Nothing new since yesterday — the board is quiet.</div>`}</div>`);

  secs.push(`<div class="card"><h3>Resume drafts ready for review</h3>
    ${(tailor.drafts || []).length ? (tailor.drafts || []).map((d) => `
      <div class="row spread" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>${esc(d.job_title)}</b> <span class="muted">· ${esc(d.company)} · for ${esc(d.consultant_name)} · score ${d.score}</span>
          <div style="margin-top:4px">
            <span class="badge">${esc(d.tailored_by === "llm" ? "AI drafted" : "keyword drafted")}</span>
            ${(d.flagged || []).length
              ? `<span class="chip warn">needs review: ${d.flagged.map(esc).join(", ")}</span>`
              : `<span class="chip">no added skills</span>`}
          </div></div>
        <button class="btn" data-draftm="${d.match_id}">Review</button>
      </div>`).join("")
      : `<div class="muted">No new drafts — top matches already have tailored resumes, or none scored 85+.</div>`}
    <div class="muted" style="margin-top:8px">Drafts are never queued automatically. Review flagged skills in the tailor view before queueing.</div></div>`);

  secs.push(`<div class="card"><div class="row spread"><h3 style="margin:0">Needs attention</h3>
    ${wd.items.length ? `<button class="btn" id="of-allq">Open queue</button>` : ""}</div>
    ${wd.items.length ? wd.items.map((w) => `
      <div class="row" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <span class="badge">${esc(w.status)}</span>
        <div><b>${esc(w.job_title)}</b> <span class="muted">· ${esc(w.company)} · ${esc(w.consultant_name)}</span>
          <div class="muted">${esc(w.note)}</div></div>
      </div>`).join("")
      : `<div class="muted" style="margin-top:8px">Pipeline is healthy — nothing going cold.</div>`}</div>`);

  $("#of-briefing").innerHTML = secs.join("");
  const allm = $("#of-allm");
  if (allm) allm.onclick = () => go("matches");
  const allq = $("#of-allq");
  if (allq) allq.onclick = () => go("queue");
  $$("[data-draftm]", el).forEach((b) => b.onclick = () => { go("matches"); });
}

/* ---------- router ---------- */
function render(tab) {
  ({overview: renderOverview, consultants: renderConsultants, jobs: renderJobs, matches: renderMatches,
    queue: renderQueue, office: renderOffice, settings: renderSettings})[tab]();
}
initTheme();
render("overview");
refreshBadges();
