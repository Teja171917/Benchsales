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

let ME = null;
async function loadMe() {
  try { ME = await api("/api/auth/me"); } catch (e) { /* leave null */ }
  if (ME && ME.can_settings === false) {
    const b = $('#tabs button[data-tab="settings"]');
    if (b) b.style.display = "none";
  }
  if (ME && ME.can_jobs === false) {
    const b = $('#tabs button[data-tab="jobs"]');
    if (b) b.style.display = "none";
  }
  return ME;
}
function scoreCls(score) {
  const n = Number(score) || 0;
  return n >= 85 ? "hot" : n >= 70 ? "warm" : "";
}
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
    const [jobs, matches, apps, briefing, feedback] = await Promise.all([
      api("/api/jobs/count"), api("/api/matches/summary"), api("/api/applications"),
      api("/api/office/briefing").catch(() => null),
      api("/api/feedback").catch(() => null),
    ]);
    const set = (id, n) => { const b = $(id); if (b) b.textContent = n > 0 ? String(n) : ""; };
    set("#nb-jobs", jobs.count);
    set("#nb-matches", matches.total);
    set("#nb-queue", apps.filter((a) => !["rejected", "withdrawn"].includes(a.status)).length);
    if (feedback) set("#nb-feedback", feedback.filter((f) => f.status === "new").length);
    if (briefing && briefing.agents) {
      const ag = briefing.agents;
      const attn = (ag.watchdog?.stale || 0) + (ag.watchdog?.links_dead || 0)
        + (ag.tailor?.drafted || 0) + (ag.tracker?.stuck || 0)
        + (ag.compliance?.issues || 0);
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

/* ---------- employment types (USA market) ---------- */
const EMP_TYPES = [["fulltime", "Full-time"], ["c2c", "C2C"], ["w2", "W2"],
  ["contract", "Contract"], ["1099", "1099"], ["c2h", "Contract-to-hire"],
  ["parttime", "Part-time"]];
const EMP_LABEL = Object.fromEntries(EMP_TYPES);
const EMP_DEFAULT = ["fulltime", "c2c", "w2"];
const AUTH_LABELS = {citizens_only: "US citizens only", citizens_gc: "Citizens / Green Card",
  no_sponsorship: "No sponsorship", sponsorship_ok: "Sponsorship OK"};
const authBadge = (t) => (t && AUTH_LABELS[t]) ? `<span class="chip">${AUTH_LABELS[t]}</span>` : "";
const authSelectOptions = (cur) => `<option value=""${cur === "" ? " selected" : ""}>Any work auth</option>` +
  Object.entries(AUTH_LABELS).map(([k, label]) =>
    `<option value="${k}"${cur === k ? " selected" : ""}>${label}</option>`).join("") +
  `<option value="none"${cur === "none" ? " selected" : ""}>Not stated in posting</option>`;
/* multi-select chip filters (testers asked for checkboxes, Nov 3 2026):
   a row passes when its value is one of the ticked keys; no ticks = all;
   the "none" key matches rows where the posting states nothing. */
function multiPasses(value, selected) {
  if (!selected || !selected.length) return true;
  if (!value) return selected.includes("none");
  return selected.includes(value);
}
const AUTH_KEYS = [...Object.keys(AUTH_LABELS), "none"];
const authKeyLabel = (k) => (k === "none" ? "Not stated in posting" : AUTH_LABELS[k]);
function authChipsHtml(selected, attr) {
  return AUTH_KEYS.map((k) => `<label class="chip-toggle"><input type="checkbox" ${attr}="${k}"${selected.includes(k) ? " checked" : ""}><span>${esc(authKeyLabel(k))}</span></label>`).join("");
}
const LEVEL_LABELS = {intern: "Intern", entry: "Entry-Level", mid: "Mid-Level",
  senior: "Senior", lead: "Lead", principal: "Principal", architect: "Architect-Level"};
const LEVEL_KEYS = [...Object.keys(LEVEL_LABELS), "none"];
const levelKeyLabel = (k) => (k === "none" ? "Not stated" : LEVEL_LABELS[k]);
const levelBadge = (l) => (l && LEVEL_LABELS[l]) ? `<span class="chip">${LEVEL_LABELS[l]}</span>` : "";
function levelChipsHtml(selected, attr) {
  return LEVEL_KEYS.map((k) => `<label class="chip-toggle"><input type="checkbox" ${attr}="${k}"${selected.includes(k) ? " checked" : ""}><span>${esc(levelKeyLabel(k))}</span></label>`).join("");
}
function tagBadges(tags) {
  return (tags || []).map((t) => `<span class="tag tag-${esc(t)}">${esc(EMP_LABEL[t] || t)}</span>`).join("");
}
/* chip row; read back with readEmp(container) */
function empChips(selected, attr) {
  return EMP_TYPES.map(([k, label]) => `<label class="chip-toggle"><input type="checkbox" ${attr}="${k}"${selected.includes(k) ? " checked" : ""}><span>${esc(label)}</span></label>`).join("");
}
function readEmp(root, attr) {
  return $$(`[${attr}]`, root).filter((c) => c.checked).map((c) => c.getAttribute(attr));
}
const ENG_TAGS = ["fulltime", "c2c", "w2", "1099", "c2h"];
function empPasses(tags, wanted, unspec) {
  if (!wanted.length) return true;
  if (!tags || !tags.length) return unspec;
  // Teja's rule (Nov 3 2026): the selection is exclusive. If a posting
  // names ANY engagement type that is not selected — a "W2" or "Full-time"
  // tag next to contract tags included — it does not belong in this view,
  // even when it also carries a selected type ("C2C or W2" included).
  // "contract"/"parttime" are duration/schedule words, never excluders.
  if (tags.some((t) => ENG_TAGS.includes(t) && !wanted.includes(t))) return false;
  return tags.some((t) => wanted.includes(t));
}

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
    <span class="row">
      <label class="btn primary">Add resumes
        <input type="file" id="c-bulk" accept=".pdf,.docx,.txt" multiple hidden>
      </label>
      <button class="btn" id="c-add">Add consultant</button>
    </span></div>
    <div class="muted" id="c-bulkmsg"></div>
    <div id="c-list" class="grid">${skelCards(3)}</div>`;
  $("#c-add").onclick = () => consultantModal(null);
  $("#c-add").onclick = () => consultantModal(null);
  $("#c-bulk").onchange = async (e) => {
    const files = Array.from(e.target.files || []);
    const box = $("#c-bulkmsg");
    if (!files.length) return;
    const done = [], failed = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      box.textContent = `Reading resume ${i + 1} of ${files.length}: ${f.name} …`;
      const fd = new FormData();
      fd.append("file", f);
      try {
        const r = await fetch(`/api/resumes/auto?kick=${i === files.length - 1 ? 1 : 0}`, {method: "POST", body: fd});
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "upload failed");
        done.push(d);
      } catch (err) { failed.push(`${f.name}: ${err.message}`); }
    }
    const lines = done.map((d) => `${d.created ? "Added" : "Updated"} <b>${esc(d.name)}</b> — ${d.skills.length} skills`
      + (d.learned_skills.length ? `, learned ${d.learned_skills.length} new` : "")
      + `, ${d.new_matches} new matches`
      + (d.needs_check ? ` — <b>needs a quick check</b>: ${esc((d.check_notes || []).join("; "))}` : ""));
    const html = (lines.length ? `<div class="okbox">${lines.join("<br>")}<br>Searching for jobs for these roles now…</div>` : "")
      + (failed.length ? `<div class="errbox">${failed.map(esc).join("<br>")}</div>` : "");
    refreshBadges();
    await renderConsultants();   // redraw the list, then show the summary
    const b2 = $("#c-bulkmsg");
    if (b2) b2.innerHTML = html;
  };
  const list = await api("/api/consultants");
  $("#c-list").innerHTML = list.map((c) => `
    <div class="card">
      <div class="row spread"><h3>${esc(c.name)}</h3>
        <span class="row">
          <button class="btn" data-edit="${c.id}">Edit</button>
          <button class="btn danger" data-del="${c.id}">Remove</button>
        </span></div>
      ${c.needs_check ? `<div class="errbox" style="margin:6px 0"><b>Needs a quick check</b>${c.check_notes ? ": " + esc(c.check_notes) : ""}
        <div style="margin-top:6px"><button class="btn" data-checked="${c.id}">Looks right</button>
        <button class="btn" data-edit="${c.id}">Fix it</button></div></div>` : ""}
      <div class="muted">${esc(c.location)}${c.visa_status ? " · " + esc(c.visa_status) : ""}</div>
      ${c.email || c.phone ? `<div class="muted">${[c.email, c.phone].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
      ${c.target_roles ? `<div class="muted"><b>Target roles:</b> ${esc(c.target_roles)}</div>` : ""}
      <div style="margin:8px 0">
        ${c.has_resume
          ? `<span class="badge fname" title="${esc(c.resume_filename)}">resume: ${esc(c.resume_filename)}</span>
             <div style="margin-top:6px">${c.skills.map((s) => `<span class="chip">${esc(s)}</span>`).join("") || '<span class="muted">no skills parsed</span>'}</div>`
          : `<span class="muted">no resume yet</span>`}
      </div>
      <div class="row">
        <label class="btn">Upload resume
          <input type="file" data-upload="${c.id}" accept=".pdf,.docx,.txt" hidden>
        </label>
        <button class="btn" data-gaps="${c.id}" data-gapsname="${esc(c.name)}">Skill gaps</button>
        <span class="muted" data-uploadmsg="${c.id}"></span>
      </div>
    </div>`).join("") || `<div class="card muted">No consultants yet. Press Add resumes (or Add consultant) above.</div>`;

  $$("[data-gaps]", el).forEach((b) => b.onclick = () => skillGapsModal(Number(b.dataset.gaps), b.dataset.gapsname));
  $$("[data-edit]", el).forEach((b) => b.onclick = async () => {
    const c = await api(`/api/consultants/${b.dataset.edit}`);
    consultantModal(c);
  });
  $$("[data-checked]", el).forEach((b) => b.onclick = async () => {
    await api(`/api/consultants/${b.dataset.checked}/checked`, {method: "POST"});
    toast("Marked as checked", "ok");
    renderConsultants();
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
      toast(`Resume parsed — ${d.skills.length} skills`
        + (d.learned_skills && d.learned_skills.length ? `, learned ${d.learned_skills.length} new` : "")
        + (d.searching_jobs ? ". Searching jobs for this role now…" : ""), "ok");
      refreshBadges();
      renderConsultants();
    } catch (e) { msg.textContent = "error: " + e.message; toast("Upload failed: " + e.message, "err"); }
  });
}

async function skillGapsModal(cid, name) {
  openModal(`<h2>Skill gaps</h2><div class="muted">Reading ${esc(name || "the consultant")}'s matches…</div>`, true);
  let d;
  try {
    d = await api(`/api/consultants/${cid}/skill-gaps`);
  } catch (e) {
    openModal(`<h2>Skill gaps</h2><div class="errbox">${esc(e.message)}</div>
      <div class="row" style="margin-top:10px"><button class="btn" onclick="closeModal()">Close</button></div>`, true);
    return;
  }
  const rows = (d.gaps || []).map((g) => `<tr>
      <td><span class="chip miss">${esc(g.skill)}</span></td>
      <td>missing in ${g.matches_missing} of ${d.matches_considered} matches</td>
      <td>${g.demand_jobs ? `wanted by ${g.demand_jobs} recent job postings` : "no recent postings counted"}</td>
    </tr>`).join("");
  openModal(`
    <div class="row spread"><h2>Skill gaps — ${esc(d.consultant_name || name || "")}</h2><button class="x" onclick="closeModal()">✕</button></div>
    <p class="muted">Skills ${esc(d.consultant_name || "their")} matches keep asking for that the resume doesn't show — across ${d.matches_considered} matches (${d.gap_count} distinct gaps). This is the coaching and verification list: if the consultant truly has one of these, confirm it with them and update the resume — BenchPilot never adds a gap skill on its own.</p>
    ${rows ? `<table class="fb-table"><tr><th>Skill</th><th>How often it blocks</th><th>Market demand</th></tr>${rows}</table>`
           : `<div class="okbox">No gaps — every match's requirements are covered by the resume, or there are no matches yet.</div>`}
    <div class="row" style="margin-top:10px"><button class="btn" onclick="closeModal()">Close</button></div>`, true);
}

function consultantModal(c) {
  c = c || {};
  const r = c.rules || {};
  const rlist = (a) => esc((a || []).join(", "));
  openModal(`
    <h2>${c.id ? "Edit" : "Add"} consultant</h2>
    <div class="kv">
      <label>Name *</label><input type="text" id="m-name" value="${esc(c.name || "")}">
      <label>Email</label><input type="email" id="m-email" value="${esc(c.email || "")}">
      <label>Phone</label><input type="text" id="m-phone" value="${esc(c.phone || "")}">
      <label>Location</label><input type="text" id="m-location" value="${esc(c.location || "")}" placeholder="Houston, TX">
      <label>Visa status</label><select id="m-visa">${(() => {
        const opts = ["", "US Citizen", "Green Card", "H1B", "H4 EAD", "OPT / STEM OPT EAD", "Other EAD", "TN", "Other"];
        const cur = c.visa_status || "";
        const all = opts.includes(cur) ? opts : [cur, ...opts];
        return all.map((o) => `<option value="${esc(o)}"${o === cur ? " selected" : ""}>${o === "" ? "Not set" : esc(o)}</option>`).join("");
      })()}</select>
      <label>LinkedIn URL</label><input type="url" id="m-li" value="${esc(c.linkedin_url || "")}">
      <label>Target roles</label><input type="text" id="m-roles" value="${esc(c.target_roles || "")}" placeholder="SDET, QA Automation Engineer, Test Automation Engineer">
      <label>Open to</label><div id="m-emp" class="chiprow">${empChips((c.emp_pref || "").split(",").filter(Boolean), "data-memp")}</div>
      <label>Notes</label><textarea id="m-notes" rows="2">${esc(c.notes || "")}</textarea>
    </div>
    <div class="muted" style="margin-bottom:8px">Target roles: the jobs this person should get, separated by commas. BenchPilot searches for these roles and only matches jobs whose title fits one of them.</div>
    <div class="muted" style="margin-bottom:8px">Open to: leave all unchecked to match every engagement type. If you tick some, jobs that explicitly list only other types (e.g. "C2C only") are not matched to this consultant.</div>
    <h3 style="margin:10px 0 6px">Standing rules</h3>
    <div class="kv">
      <label>Job titles</label><input type="text" id="m-rules-titles" value="${rlist(r.titles)}" placeholder="Java Developer, Data Engineer">
      <label>Locations</label><input type="text" id="m-rules-locations" value="${rlist(r.locations)}" placeholder="Houston, TX, Austin, TX">
      <label>Exclude keywords</label><input type="text" id="m-rules-exkw" value="${rlist(r.exclude_keywords)}" placeholder="clearance, secret">
      <label>Exclude clients</label><input type="text" id="m-rules-excl" value="${rlist(r.exclude_clients)}" placeholder="Acme Corp">
      <label>Min rate (annual $)</label><input type="number" id="m-rules-rate" min="0" step="1000" value="${r.min_rate ? esc(String(r.min_rate)) : ""}" placeholder="120000">
      <label>Remote only</label><input type="checkbox" id="m-rules-remote" ${r.remote_only ? "checked" : ""}>
    </div>
    <div class="muted" style="margin-bottom:8px">Standing rules gate the agents only: the Tailor won't draft for, and the office won't queue, jobs outside these rules. Matching and scores don't change. Lists are comma-separated; leave everything blank to let the agents act on every match.</div>
    <div class="row"><button class="btn primary" id="m-save">Save</button>
    <button class="btn" id="m-cancel">Cancel</button></div>`);
  $("#m-cancel").onclick = closeModal;
  $("#m-save").onclick = async () => {
    const split = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
    const data = {name: $("#m-name").value, email: $("#m-email").value,
      phone: $("#m-phone").value, location: $("#m-location").value,
      visa_status: $("#m-visa").value, linkedin_url: $("#m-li").value,
      notes: $("#m-notes").value,
      emp_pref: readEmp($("#m-emp"), "data-memp").join(","),
      target_roles: $("#m-roles").value.trim(),
      rules: {titles: split($("#m-rules-titles").value),
        locations: split($("#m-rules-locations").value),
        exclude_keywords: split($("#m-rules-exkw").value),
        exclude_clients: split($("#m-rules-excl").value),
        remote_only: $("#m-rules-remote").checked,
        min_rate: Number($("#m-rules-rate").value) || 0}};
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
      ${j.remote_flag ? `<span class="badge">remote</span>` : ""}${tagBadges(j.emp_tags)}${authBadge(j.auth_tag)}${levelBadge(j.exp_level)}</div>
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
  if (job.id && job.description === undefined && !opts.unsaved) {
    try {
      const full = await api(`/api/jobs/${job.id}`);
      const ix = jobsCache.findIndex((x) => x.id === job.id);
      if (ix >= 0) jobsCache[ix] = full;
      job = full;
    } catch (e) { /* fall through with the light row */ }
  }
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
const jobsDefaults = () => ({source: "", q: "", remote: false, location: "", emp: EMP_DEFAULT.slice(),
  unspec: true, posted: "", sort: "newest", auths: [], levels: []});
let jobsFilter = jobsDefaults();
let jobsCache = [];
let jobsShown = 100;
async function renderJobs() {
  const el = $("#tab-jobs");
  if (!ME) await loadMe();
  if (ME && ME.can_jobs === false) {
    el.innerHTML = `<div class="row spread"><h2>Jobs</h2></div>
      <div class="card muted">The job pool runs in the backend — collection keeps going and every posting still flows into Matches. The raw pool itself is owner-only, so there's nothing to load here.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="row spread"><h2>Jobs</h2>
      <button class="btn primary" id="j-run">Run job collection</button></div>
    <div class="muted" id="j-fresh" style="margin:-4px 0 10px"></div>
    <div class="progress" id="j-prog"></div>
    <div class="card" id="j-empbar"><div class="row" style="gap:12px;flex-wrap:wrap">
      <b>Employment type</b>
      <span class="chiprow" id="j-emp">${empChips(jobsFilter.emp, "data-jemp")}</span>
      <label class="fcheck"><input type="checkbox" id="j-unspec"${jobsFilter.unspec ? " checked" : ""}> include jobs with no type listed</label></div>
      <div class="muted" style="margin-top:6px">USA market. Applies to live search and the job board below. A job counts as C2C / W2 when its type or description says so (and "no C2C" / "W2 only" are understood).</div></div>
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
        <div id="j-authbar"><span class="flabel">Work auth — tick any</span>
          <span class="chiprow" id="j-auth">${authChipsHtml(jobsFilter.auths, "data-jauth")}</span></div>
        <div id="j-levelbar"><span class="flabel">Experience level — tick any</span>
          <span class="chiprow" id="j-level">${levelChipsHtml(jobsFilter.levels, "data-jlevel")}</span></div>
        <div><label class="flabel" for="j-loc">Location</label>
          <input type="text" id="j-loc" placeholder="city, state…" value="${esc(jobsFilter.location)}"></div>
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
  $("#j-authbar").addEventListener("change", () => {
    jobsFilter.auths = readEmp($("#j-auth"), "data-jauth");
    applyJobFilters();
  });
  $("#j-levelbar").addEventListener("change", () => {
    jobsFilter.levels = readEmp($("#j-level"), "data-jlevel");
    applyJobFilters();
  });
  $("#j-empbar").addEventListener("change", () => {
    jobsFilter.emp = readEmp($("#j-emp"), "data-jemp");
    jobsFilter.unspec = $("#j-unspec").checked;
    applyJobFilters();
  });
  $("#j-posted").onchange = (e) => { jobsFilter.posted = e.target.value; applyJobFilters(); };
  $("#j-sort").onchange = (e) => { jobsFilter.sort = e.target.value; applyJobFilters(); };
  $("#j-remote").onchange = (e) => { jobsFilter.remote = e.target.checked; applyJobFilters(); };
  $("#j-reset").onclick = () => {
    jobsFilter = jobsDefaults();
    $("#j-q").value = ""; $("#j-loc").value = "";
    $$("[data-jauth]").forEach((c) => c.checked = false);
    $$("[data-jlevel]").forEach((c) => c.checked = false);
    $("#j-source").value = "";
    $$("[data-jemp]").forEach((c) => c.checked = jobsFilter.emp.includes(c.dataset.jemp));
    $("#j-unspec").checked = jobsFilter.unspec;
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
        {method: "POST", body: JSON.stringify({title, location,
          emp: jobsFilter.emp, include_unspecified: jobsFilter.unspec})});
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
            <td><b>${esc(j.title)}</b>${j.salary ? `<div class="muted">${esc(j.salary)}</div>` : ""}<div>${tagBadges(j.emp_tags)}${authBadge(j.auth_tag)}${levelBadge(j.exp_level)}</div></td>
            <td>${esc(j.company)}</td>
            <td>${esc(j.location)}${j.remote_flag && !/remote/i.test(j.location || "") ? " (remote)" : ""}</td>
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
  try {
    jobsCache = await api("/api/jobs?limit=1000&light=1");
  } catch (e) {
    el.innerHTML = `<div class="card muted">The job pool didn't load (${esc(e.message)}). <button class="btn" id="j-retry">Retry</button></div>`;
    const rt = $("#j-retry");
    if (rt) rt.onclick = () => loadJobs();
    return;
  }
  jobsShown = 100;
  applyJobFilters();
  // the dropdown fills ride along in parallel; they never block the table
  api("/api/jobs/cities").then((marketCities) => {
    const citySel0 = $("#mt-city");
    if (!citySel0) return;
    if (matchFilter.city && !marketCities.some((c) => c.city === matchFilter.city)) matchFilter.city = "";
    citySel0.innerHTML = `<option value="">All cities</option>` +
      marketCities.map((c) => `<option value="${esc(c.city)}"${matchFilter.city === c.city ? " selected" : ""}>${esc(c.city)} (${c.jobs})</option>`).join("");
  }).catch(() => {});
  api("/api/sources/status").then((srcs) => {
    const sel = $("#j-source");
    if (!sel) return;
    sel.innerHTML = `<option value="">All sources</option>` +
      srcs.filter((s) => s.name !== "urlimport")
        .map((s) => `<option value="${s.name}"${jobsFilter.source === s.name ? " selected" : ""}>${esc(s.label)}</option>`).join("");
  }).catch(() => {});
}
function jobMatches(j) {
  const f = jobsFilter;
  if (f.source && j.source !== f.source) return false;
  if (!multiPasses(j.auth_tag, f.auths)) return false;
  if (!multiPasses(j.exp_level, f.levels)) return false;
  if (f.remote && !j.remote_flag) return false;
  if (!empPasses(j.emp_tags, f.emp, f.unspec)) return false;
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
function applyJobFilters(resetShown) {
  if (resetShown !== false) jobsShown = 100;
  const list = jobsCache.filter(jobMatches);
  const ts = (j) => { const d = new Date(j.posted_at || 0); return isNaN(d.getTime()) ? 0 : d.getTime(); };
  const s = jobsFilter.sort;
  list.sort((a, b) => s === "title" ? (a.title || "").localeCompare(b.title || "")
    : s === "company" ? (a.company || "").localeCompare(b.company || "")
    : s === "oldest" ? ts(a) - ts(b) : ts(b) - ts(a));
  const cnt = $("#j-count");
  const page = list.slice(0, jobsShown);
  if (cnt) cnt.textContent = `Showing ${page.length} of ${list.length} jobs (${jobsCache.length} in the pool)`;
  $("#j-list").innerHTML = `<div class="card" style="padding:0"><table class="jobs">
    <tr><th>Title</th><th>Company</th><th>Location</th><th>Source</th><th>Posted</th><th></th></tr>
    ${page.map((j) => `<tr data-jobid="${j.id}">
      <td><b>${esc(j.title)}</b>${j.salary ? `<div class="muted">${esc(j.salary)}</div>` : ""}<div>${tagBadges(j.emp_tags)}</div></td>
      <td>${esc(j.company)}</td><td>${esc(j.location)}${j.remote_flag && !/remote/i.test(j.location || "") ? " (remote)" : ""}</td>
      <td><span class="badge ${esc(j.source)}">${esc(j.source)}</span></td>
      <td class="muted" title="${esc((j.posted_at || "").slice(0, 10))}">${j.posted_at ? esc(ago(j.posted_at)) : "—"}</td>
      <td>${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">view</a>` : ""}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">No jobs match these filters.</td></tr>`}
    </table></div>
    ${list.length > jobsShown ? `<div class="row" style="justify-content:center;margin-top:10px"><button class="btn" id="j-more">Show more (${list.length - jobsShown} more)</button></div>` : ""}`;
  const more = $("#j-more");
  if (more) more.onclick = () => { jobsShown += 100; applyJobFilters(false); };
}
async function updateFreshness() {
  const f = $("#j-fresh");
  if (!f) return;
  try {
    const st = await api("/api/collect/status");
    if (st.running) {
      f.textContent = st.phase
        ? `Collection running right now — ${st.phase} phase (${st.phase_seconds || 0}s in)…`
        : "Collection running right now…";
      return;
    }
    const last = st.last_result
      ? ` (+${st.last_result.jobs_new} new jobs, +${st.last_result.matches_new} new matches)` : "";
    if (st.interval_minutes > 0) {
      f.textContent = `Auto-refresh every ${st.interval_minutes} min · last run ${ago(st.last_run_at)}${last}`
        + (st.auto_queries && st.queries && st.queries.length ? ` · searching ${st.queries.length} role/place combos taken from the resumes` : "");
    } else {
      f.textContent = st.last_run_at
        ? `Auto-refresh is off · last run ${ago(st.last_run_at)}${last} — click "Run job collection" for fresh data`
        : `Auto-refresh is off — click "Run job collection" to pull fresh jobs`;
    }
  } catch (e) { f.textContent = ""; }
}
async function runCollection() {
  const prog = $("#j-prog");
  const say = (html) => { if (prog) prog.innerHTML = html; };
  try {
    const r = await api("/api/collect", {method: "POST"});
    say(`<div class="muted">${r && r.started === false
      ? "A collection is already running — watching for it to finish…"
      : "Collection started in the background — it keeps going even if you leave this page. Watching for it to finish…"}</div>`);
    if (!prog) toast("Collection started — running in the background", "ok");
    // poll the status until the run lands (collections run in the
    // background now; the request itself returns instantly)
    let st = null;
    for (let i = 0; i < 140; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      st = await api("/api/collect/status").catch(() => null);
      if (st && !st.running && st.last_result) break;
      if (prog && st) prog.querySelector(".muted").textContent =
        `Collecting… still running (${Math.round((i + 1) * 3)}s)${st.phase ? ` — ${st.phase} phase` : ""} — sources answer at very different speeds.`;
    }
    if (st && st.last_result) {
      const lr = st.last_result;
      let lines = [];
      try {
        const srcs = await api("/api/sources/status");
        lines = srcs.filter((x) => x.last_run && x.last_run.status).map((x) =>
          `${x.name}: ${x.last_run.status}${x.last_run.status === "ok" ? ` — found ${x.last_run.jobs || 0}, ${x.last_run.new || 0} new` : ""}`);
      } catch (e) { /* lines are a nicety */ }
      const phaseLine = lr.phases ? Object.entries(lr.phases).map(([k, v]) =>
        `${k} ${v.seconds}s${v.status && v.status !== "ok" ? ` (${v.status})` : ""}`).join(" · ") : "";
      say(`<div class="okbox">Done — ${lr.jobs_new || 0} new jobs, ${lr.matches_new || 0} new matches.${phaseLine ? `<br>Phases: ${esc(phaseLine)}` : ""}<br>${lines.map(esc).join("<br>")}</div>`);
      if (!prog) toast(`Done — ${lr.jobs_new || 0} new jobs, ${lr.matches_new || 0} new matches`, "ok");
    } else {
      say(`<div class="muted">The collection is taking longer than usual — it's still running in the background and the freshness line above will update when it lands.</div>`);
    }
    if ($("#j-list")) loadJobs();
    if ($("#j-fresh")) updateFreshness();
    refreshBadges();
  } catch (e) {
    say(`<div class="errbox">Collection failed: ${esc(e.message)}</div>`);
    if (!prog) toast("Collection failed: " + e.message, "err");
  }
}

/* ================= MATCHES ================= */
let matchFilter = {consultant_id: "", min_score: 0, source: "", sort: "best",
  emp: EMP_DEFAULT.slice(), unspec: true, city: "", work: [], auths: [], levels: []};
// the matches list is fetched ONCE per consultant/threshold choice and
// kept here: city / sort / work-type / source clicks then filter this
// copy instantly instead of re-downloading the whole list every time
let matchesCache = {key: null, rows: null};
let matchShowCount = 100;
function cityOf(m) {
  if (m.city !== undefined && m.city !== null) return m.city;
  let loc = (m.location || "").trim();
  if (/^remote\s*-\s*/i.test(loc)) loc = loc.replace(/^remote\s*-\s*/i, "");
  if (!loc) return "";
  const parts = loc.split(",").map((x) => x.trim());
  if (parts.length >= 2) {
    // "Locality, Harris County" is a district, not a city (matches the
    // backend's city list); NYC boroughs mean New York
    if (/ county$/i.test(parts[1])) return "";
    if (["manhattan", "brooklyn", "queens", "bronx", "staten island"]
        .includes(parts[1].toLowerCase())) return "New York";
  }
  return parts[0];
}
function workTypeOf(m) {
  if (m.remote_flag) return "remote";
  const t = `${m.job_title || ""} ${m.location || ""}`.toLowerCase();
  if (/\bremote\b|anywhere/.test(t)) return "remote";
  if (/hybrid/.test(t)) return "hybrid";
  return "onsite";
}
function workBadge(m) {
  const w = workTypeOf(m);
  return w === "remote" ? `<span class="badge">remote</span>`
    : w === "hybrid" ? `<span class="badge">hybrid</span>` : "";
}
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
          <option value="new"${matchFilter.sort === "new" ? " selected" : ""}>Latest post first</option>
          <option value="low"${matchFilter.sort === "low" ? " selected" : ""}>Lowest score first</option>
        </select></div>
      <div><label class="flabel" for="mt-city">City</label>
        <select id="mt-city"><option value="">All cities</option></select></div>
      <div><span class="flabel">&nbsp;</span>
        <button class="btn primary" id="mt-go">Apply filters</button></div>
    </div>
    <div class="row" style="gap:12px;flex-wrap:wrap;margin-top:10px"><b>Work type</b>
      <span class="chiprow" id="mt-work">${workChipsHtml()}</span>
      <span class="muted">pick any combination</span>
    </div>
    <div class="row" style="gap:12px;flex-wrap:wrap;margin-top:10px"><b>Work auth</b>
      <span class="chiprow" id="mt-auth">${authChipsHtml(matchFilter.auths, "data-mauth")}</span>
      <span class="muted">tick any — what the posting states (citizen / GC / EAD / sponsorship)</span>
    </div>
    <div class="row" style="gap:12px;flex-wrap:wrap;margin-top:10px"><b>Experience level</b>
      <span class="chiprow" id="mt-level">${levelChipsHtml(matchFilter.levels, "data-mlevel")}</span>
      <span class="muted">read from each posting's title and the years it asks for</span>
    </div>
    <div class="row" style="gap:12px;flex-wrap:wrap;margin-top:10px"><b>Employment type</b>
      <span class="chiprow" id="mt-emp">${empChips(matchFilter.emp, "data-memp2")}</span>
      <label class="fcheck"><input type="checkbox" id="mt-unspec"${matchFilter.unspec ? " checked" : ""}> include jobs with no type listed</label></div></div>
    <div id="mt-count" class="muted" style="margin:0 2px 8px"></div>
    <div id="mt-list" class="grid"></div>`;
  $("#mt-go").onclick = () => {
    matchFilter.consultant_id = $("#mt-c").value;
    matchFilter.min_score = Number($("#mt-s").value) || 0;
    matchFilter.source = $("#mt-src").value;
    matchFilter.sort = $("#mt-sort").value;
    matchFilter.emp = readEmp($("#mt-emp"), "data-memp2");
    matchFilter.unspec = $("#mt-unspec").checked;
    loadMatches();
  };
  // city, sort and work type filter instantly, without the Apply button
  $("#mt-city").onchange = () => { matchFilter.city = $("#mt-city").value; loadMatches(); };
  $("#mt-sort").onchange = () => { matchFilter.sort = $("#mt-sort").value; loadMatches(); };
  $$("#mt-auth input[data-mauth]").forEach((c) => { c.onchange = () => { matchFilter.auths = readEmp($("#mt-auth"), "data-mauth"); loadMatches(); }; });
  $$("#mt-level input[data-mlevel]").forEach((c) => { c.onchange = () => { matchFilter.levels = readEmp($("#mt-level"), "data-mlevel"); loadMatches(); }; });
  bindWorkChips();
  // The list loads FIRST. Each dropdown then fills on its own below:
  // sequential awaits here once meant one slow or failing call (a
  // locked database made /api/consultants 500) killed the handlers,
  // the list, and every filter after it — the consultant filter
  // simply never appeared.
  loadMatches(true);
  api("/api/consultants").then((cs) => {
    $("#mt-c").innerHTML = `<option value="">All consultants</option>` +
      cs.map((c) => `<option value="${c.id}"${String(c.id) === String(matchFilter.consultant_id) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  }).catch(() => {});
  api("/api/sources/status").then((srcs) => {
    $("#mt-src").innerHTML = `<option value="">All sources</option>` +
      srcs.filter((s) => s.name !== "urlimport")
        .map((s) => `<option value="${s.name}"${matchFilter.source === s.name ? " selected" : ""}>${esc(s.label)}</option>`).join("");
  }).catch(() => {});
  // the City dropdown is filled HERE, by the Matches view itself —
  // it used to be filled as a side effect of loading the Jobs view,
  // so it stayed empty unless Jobs happened to load at the right time
  api("/api/jobs/cities").then((cities) => {
    if (matchFilter.city && !cities.some((c) => c.city === matchFilter.city)) matchFilter.city = "";
    $("#mt-city").innerHTML = `<option value="">All cities</option>` +
      cities.map((c) => `<option value="${esc(c.city)}"${matchFilter.city === c.city ? " selected" : ""}>${esc(c.city)} (${c.jobs})</option>`).join("");
  }).catch(() => {});
}
async function loadMatches(force) {
  matchShowCount = 100;
  const key = `${matchFilter.consultant_id}|${matchFilter.min_score || 0}`;
  if (force || !matchesCache.rows || matchesCache.key !== key) {
    const el = $("#mt-list");
    el.innerHTML = skelCards(6);
    // only send consultant_id when one is chosen: an empty "consultant_id="
    // is not a valid integer and strict API validation would reject it
    const mq = new URLSearchParams({min_score: String(matchFilter.min_score || 0)});
    if (matchFilter.consultant_id) mq.set("consultant_id", matchFilter.consultant_id);
    matchesCache = {key, rows: await api(`/api/matches?${mq}`)};
  }
  renderMatchCards();
}
function workChipsHtml() {
  const opts = [["", "All"], ["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]];
  return opts.map(([k, label]) => {
    const on = k === "" ? matchFilter.work.length === 0 : matchFilter.work.includes(k);
    return `<label class="chip-toggle"><input type="checkbox" data-work="${k}"${on ? " checked" : ""}><span>${label}</span></label>`;
  }).join("");
}
function bindWorkChips() {
  $$("#mt-work input[data-work]").forEach((r) => { r.onchange = () => {
    if (r.dataset.work === "") matchFilter.work = [];
    else if (r.checked) matchFilter.work = [...new Set([...matchFilter.work, r.dataset.work])];
    else matchFilter.work = matchFilter.work.filter((w) => w !== r.dataset.work);
    const box = $("#mt-work");
    if (box) { box.innerHTML = workChipsHtml(); bindWorkChips(); }
    loadMatches();
  }; });
}
function renderMatchCards() {
  const el = $("#mt-list");
  let ms = [...(matchesCache.rows || [])];
  if (matchFilter.source) ms = ms.filter((m) => m.source === matchFilter.source);
  const total = ms.length;
  ms = ms.filter((m) => empPasses(m.emp_tags, matchFilter.emp, matchFilter.unspec));
  if (matchFilter.city) ms = ms.filter((m) => cityOf(m) === matchFilter.city);
  if (matchFilter.work.length) ms = ms.filter((m) => matchFilter.work.includes(workTypeOf(m)));
  ms = ms.filter((m) => multiPasses(m.auth_tag, matchFilter.auths));
  ms = ms.filter((m) => multiPasses(m.exp_level, matchFilter.levels));
  const postedTs = (m) => { const t = Date.parse(m.posted_at || ""); return isNaN(t) ? 0 : t; };
  if (matchFilter.sort === "low") ms.sort((a, b) => a.score - b.score);
  else if (matchFilter.sort === "new") ms.sort((a, b) => (postedTs(b) - postedTs(a)) || (b.score - a.score));
  else ms.sort((a, b) => (b.score - a.score) || (postedTs(b) - postedTs(a)));
  const cnt = $("#mt-count");
  if (cnt) cnt.textContent = ms.length === total ? `${ms.length} matches`
    : `Showing ${ms.length} of ${total} matches`;
  const totalFiltered = ms.length;
  el.innerHTML = ms.slice(0, matchShowCount).map((m) => `
    <div class="card">
      <div class="row spread">
        <div><b>${esc(m.job_title)}</b><div class="muted">${esc(m.company)}${m.salary ? ` · 💰 ${esc(m.salary)}` : ""}${m.posted_at ? ` · 📅 posted ${esc(ago(m.posted_at))}` : ""}</div>
          <div>${tagBadges(m.emp_tags)}${authBadge(m.auth_tag)}${levelBadge(m.exp_level)}</div></div>
        <span class="badge ${esc(m.source)}">${esc(m.source)}</span>
      </div>
      ${m.visa_ok === false ? `<div style="margin-top:6px;color:#d64545"><b>Visa conflict:</b> posting says “${esc(AUTH_LABELS[m.auth_tag] || m.auth_tag)}” — ${esc(m.consultant_name)} is ${esc(m.consultant_visa || "—")}</div>` : ""}
      <div class="row" style="margin:8px 0">
        <span class="score-num ${scoreCls(m.score)}">${m.score}</span>
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
        <button class="btn" data-applyplan="${m.id}">Apply plan</button>
        <button class="btn primary" data-queue="${m.id}">Queue for apply</button>
      </div>
    </div>`).join("") || `<div class="card muted">${(matchFilter.city || matchFilter.work.length)
      ? "No matches with this city / work-type selection — try All cities or a different work type."
      : "No matches at this threshold. Run a job collection first, or lower the match threshold in Settings."}</div>`;
  if (totalFiltered > matchShowCount) {
    const more = document.createElement("div");
    more.className = "card";
    more.innerHTML = `<button class="btn" id="mt-more" style="width:100%">Show more — ${totalFiltered - matchShowCount} more matches</button>`;
    el.appendChild(more);
    $("#mt-more").onclick = () => { matchShowCount += 100; renderMatchCards(); };
  }
  $$("[data-tailor]", el).forEach((b) => b.onclick = () => tailorModal(Number(b.dataset.tailor)));
  $$("[data-applyplan]", el).forEach((b) => b.onclick = () => applyPlanModal(Number(b.dataset.applyplan)));
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
async function applyPlanModal(mid) {
  openModal(`<h2>Apply plan</h2><div class="muted">Checking the posting and reading its application form…</div>`, true);
  let plan;
  try {
    plan = await api(`/api/matches/${mid}/apply-plan`, {method: "POST"});
  } catch (e) {
    openModal(`<h2>Apply plan</h2><div class="errbox">${esc(e.message)}</div>
      <div class="row" style="margin-top:10px"><button class="btn" onclick="closeModal()">Close</button></div>`, true);
    return;
  }
  const verdict = {
    ready: `<span class="fb-chip st-done">Ready to apply</span> Live posting, and every required field is answered by ${esc(plan.consultant_name)}'s BenchPilot data.`,
    blocked: `<span class="fb-chip st-new">A person must answer ${plan.blockers.length} field(s) first</span> The posting is live, but the fields below in red can't be answered from BenchPilot data — the plan stops there rather than guessing.`,
    dead: `<span class="fb-chip st-dismissed">Posting is gone</span> No point applying — it would go nowhere.`,
    unknown: `<span class="fb-chip st-planned">Couldn't verify</span> The posting couldn't be checked automatically (login wall, script-driven page, or network issue). Open it and check by eye.`,
    no_url: `<span class="fb-chip st-planned">No application link</span> This job has no apply link on file.`,
  }[plan.verdict] || "";
  const rows = (plan.fields || []).map((f) => {
    const st = {filled: "✓ ready", upload: "📎 attach", unanswered: "✋ needs a person",
                skipped: "— optional, left blank"}[f.status] || f.status;
    return `<tr><td>${esc(f.field)}${f.required ? ' <span class="muted">(required)</span>' : ""}</td>
      <td>${esc(f.value)}</td><td>${st}</td></tr>`;
  }).join("");
  openModal(`
    <div class="row spread"><h2>Apply plan</h2><button class="x" onclick="closeModal()">✕</button></div>
    <p><strong>${esc(plan.job_title)}</strong> at <strong>${esc(plan.company)}</strong> — for ${esc(plan.consultant_name)}</p>
    <p>${verdict}</p>
    <p class="muted">Liveness: ${esc(plan.liveness_detail)}${plan.url ? ` · <a href="${esc(plan.url)}" target="_blank" rel="noopener">Open the posting</a>` : ""}</p>
    <p class="muted">Resume: ${plan.has_tailored_resume ? "tailored version ready in BenchPilot" : "no tailored version yet — tailor it first for a stronger application"} · Cover letter: ${plan.has_cover_letter ? "saved" : "none saved"}</p>
    ${rows ? `<table class="fb-table"><tr><th>Form field</th><th>Value from BenchPilot</th><th>Status</th></tr>${rows}</table>` : ""}
    <div class="muted" style="margin-top:10px">This is a plan only — BenchPilot does not fill in or submit anything on the employer's site. A person applies using this map, or approves a pilot submission.</div>
    <div class="row" style="margin-top:10px"><button class="btn" onclick="closeModal()">Close</button></div>`, true);
}

async function tailorModal(mid) {
  openModal(`<h2>Tailoring resume…</h2><div class="muted">Working…</div>`, true);
  let t;
  try {
    t = await api(`/api/matches/${mid}/tailor`, {method: "POST"});
  } catch (e) {
    openModal(`<h2>Tailor</h2><div class="errbox">${esc(e.message)}</div>
      <button class="btn" onclick="document.getElementById('modal-root').innerHTML=''">Close</button>`);
    return;
  }
  async function render() {
    const full = await api(`/api/tailored/${t.id}`);
    const d = diffHtml(full.original_text || "", full.tailored_text || "");
    const flagged = full.added_skills_flagged || [];
    const confirmed = full.user_confirmed_skills || [];
    const missing = (t.missing_skills || []).filter((m) => !confirmed.includes(m.skill));
    const score = t.score;
    openModal(`
      <div class="row spread"><h2>Tailored resume</h2>
        <span class="badge">${esc(t.tailored_by === "llm" ? "AI tailored" : "keyword tailored")}</span></div>
      ${flagged.length ? `<div class="warnbox"><b>Warning — possible added skills:</b> ${flagged.map(esc).join(", ")}.
        These were detected in the tailored text but are not in the original resume.
        <label class="row" style="margin-top:6px"><input type="checkbox" id="tw-ack"> I acknowledge — these are accurate for the candidate</label></div>` : ""}
      ${missing.length ? `<div class="missbox"><b>Missing skills for this match${score != null ? ` (${score}%)` : ""}:</b>
        <div class="muted" style="margin:4px 0 8px">Tick the ones the candidate actually has — they get added to the tailored resume. <span class="hot">🔥</span> = in demand across recent postings.</div>
        <div>${missing.map((m) => `<label class="chip"><input type="checkbox" class="tw-miss" value="${esc(m.skill)}">${esc(m.skill)}${m.in_demand ? ` <span class="hot" title="${m.demand_jobs} recent postings mention this">🔥</span>` : ""}</label>`).join("")}</div>
        ${confirmed.length ? `<div class="muted" style="margin-top:8px">Added by you: ${confirmed.map(esc).join(", ")}</div>` : ""}
        <label class="row" style="margin-top:8px"><input type="checkbox" id="tw-confirm"> I confirm the candidate has the ticked skills</label>
        <div class="row" style="margin-top:6px"><button class="btn" id="tw-add">Add selected to resume</button></div>
      </div>` : ""}
      <div class="split">
        <div><h3>Original</h3><pre class="doc">${d.orig}</pre></div>
        <div><h3>Tailored</h3><pre class="doc">${d.tailored}</pre></div>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn primary" id="tw-queue">Save &amp; queue for apply</button>
        <button class="btn" id="tw-dl">Download tailored (.txt)</button>
        <button class="btn" id="tw-cl">Cover letter</button>
        <button class="btn" id="tw-close">Close</button>
      </div>
      <div id="tw-cl-box"></div>`, true);
    $("#tw-close").onclick = closeModal;
    $("#tw-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = "data:text/plain;charset=utf-8," + encodeURIComponent(full.tailored_text || "");
      a.download = "tailored-resume.txt";
      a.click();
    };
    $("#tw-cl").onclick = async () => {
      const box = $("#tw-cl-box");
      box.innerHTML = `<div class="muted" style="margin-top:12px">Writing the cover letter…</div>`;
      try {
        const cl = await api(`/api/matches/${mid}/cover-letter`, {method: "POST"});
        box.innerHTML = `
          <h3 style="margin:14px 0 6px">Cover letter <span class="muted">(${cl.made_by === "llm" ? "written by AI" : "template — no AI key working in this workspace"})</span></h3>
          <pre class="doc">${esc(cl.text)}</pre>
          <div class="row" style="margin-top:8px">
            <button class="btn" id="tw-cl-copy">Copy letter</button>
            <button class="btn" id="tw-cl-dl">Download letter (.txt)</button>
          </div>`;
        $("#tw-cl-copy").onclick = async () => {
          try { await navigator.clipboard.writeText(cl.text); toast("Cover letter copied", "ok"); }
          catch (e) { toast("Copy failed — select the letter text manually", "err"); }
        };
        $("#tw-cl-dl").onclick = () => {
          const a = document.createElement("a");
          a.href = "data:text/plain;charset=utf-8," + encodeURIComponent(cl.text);
          a.download = "cover-letter.txt";
          a.click();
        };
      } catch (e) {
        box.innerHTML = `<div class="errbox" style="margin-top:12px">${esc(e.message)}</div>`;
      }
    };
    const addBtn = $("#tw-add");
    if (addBtn) addBtn.onclick = async () => {
      const sel = [...document.querySelectorAll(".tw-miss:checked")].map((c) => c.value);
      const conf = $("#tw-confirm");
      if (!sel.length) { toast("Tick at least one missing skill.", "err"); return; }
      if (!conf || !conf.checked) { toast("Please confirm the candidate has these skills.", "err"); return; }
      try {
        const r = await api(`/api/tailored/${t.id}/add-skills`,
          {method: "POST", body: JSON.stringify({skills: sel, confirmed: true})});
        toast(`Added ${r.added.length} skill${r.added.length === 1 ? "" : "s"} to the resume`, "ok");
        await render();
      } catch (e) { toast(e.message, "err"); }
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
  }
  try {
    await render();
  } catch (e) {
    openModal(`<h2>Tailor</h2><div class="errbox">${esc(e.message)}</div>
      <button class="btn" onclick="document.getElementById('modal-root').innerHTML=''">Close</button>`);
  }
}

/* ================= APPLY QUEUE ================= */
let queueFilter = {consultant: ""};
async function renderQueue() {
  const el = $("#tab-queue");
  el.innerHTML = `<div class="row spread"><h2>Apply Queue</h2></div>
    <div class="card explainer"><b>What this board is:</b> your apply worklist. Every card is a job already matched to a consultant, with its tailored resume attached. <b>Nothing is submitted automatically</b> — a recruiter opens the posting, applies on the employer's site with the attached resume, then drags the card along (Queued → Applied → Interview → Placed). Cards land here when you queue a match, or automatically when the Tailor agent drafts a resume at 65+. If the owner connects an application inbox in Settings, portal confirmation emails flip cards to Applied on their own — watch Activity for “Marked Applied from a … confirmation email”.</div>
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
            ${a.tailored_resume_id ? `<button class="btn" data-resume="${a.match_id}">Resume</button>` : ""}
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
    $$("[data-resume]", el).forEach((b) => b.onclick = () => tailorModal(Number(b.dataset.resume)));
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
  if (!ME) await loadMe();
  if (ME && ME.can_settings === false) {
    el.innerHTML = `<div class="row spread"><h2>Settings</h2></div>
      <div class="card muted">Settings are restricted to the owner account — API keys and collection controls live there. Ask the owner if something needs changing.</div>`;
    return;
  }
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
      <div class="muted" style="margin-top:8px">Dice jobs come from Dice's own free connector. Indeed, LinkedIn, Glassdoor and ZipRecruiter jobs come through JSearch (needs the RapidAPI key). Any single posting can also be added with <b>Import URL</b>.</div>
      <div class="row" style="margin-top:10px"><button class="btn" id="s-portcheck">Check portal access</button>
        <span class="muted">Tests whether this server can reach each portal.</span></div>
      <div id="s-portres" style="margin-top:8px"></div>
    </div>
    <div class="card"><h3>USA market</h3>
      <label class="toggle"><input type="checkbox" id="s-usa"${s.usa_only === "0" ? "" : " checked"}> USA jobs only (drop postings that clearly name a non-US location; blank / "Remote" are kept)</label>
      <div style="margin-top:10px"><b>Employment types to collect</b>
        <div class="chiprow" id="s-emp" style="margin-top:6px">${empChips((s.collect_emp_types || "fulltime,c2c,w2").split(",").filter(Boolean), "data-semp")}</div>
        <div class="muted" style="margin-top:6px">Steers the Adzuna and JSearch queries (C2C, W2 and 1099 roles are all requested as "contractor" from JSearch). Everything fetched is still tagged, so you can narrow further on the Jobs tab.</div></div>
    </div>
    <div class="card"><h3>API keys</h3>
      <div class="kv">
        <label>Adzuna app id</label><input type="text" id="s-adzid" value="${esc(s.adzuna_app_id || "")}">
        <label>Adzuna app key</label><input type="password" id="s-adzkey" value="${esc(s.adzuna_app_key || "")}" placeholder="${s.adzuna_app_key ? "saved (hidden)" : ""}">
        <label>RapidAPI key (JSearch)</label><input type="password" id="s-rapid" value="${esc(s.rapidapi_key || "")}" placeholder="${s.rapidapi_key ? "saved (hidden)" : ""}">
        <label>LLM base URL</label><input type="text" id="s-llmurl" value="${esc(s.llm_base_url || "")}" placeholder="https://api.openai.com/v1">
        <label>LLM API key</label><input type="password" id="s-llmkey" value="${esc(s.llm_api_key || "")}" placeholder="${s.llm_api_key ? "saved (hidden)" : ""}">
        <label>LLM model</label><input type="text" id="s-llmmodel" value="${esc(s.llm_model || "")}" placeholder="gpt-4o-mini">
        <label>Tailor resumes for matches of</label><input type="number" id="s-tcut" min="30" max="100" value="${esc(s.tailor_cutoff || "65")}" placeholder="65">
        <label>Max drafts per day</label><input type="number" id="s-tmax" min="1" max="50" value="${esc(s.tailor_max_per_run || "10")}" placeholder="10">
      </div>
      <div class="muted">Keys are shown masked. They can also be set as Replit Secrets (ADZUNA_APP_ID, ADZUNA_APP_KEY, RAPIDAPI_KEY, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), which survive Republish. The LLM is also used to read resumes. Resume text is sent to that AI provider. Without an LLM key, tailoring and resume reading use the built-in simple methods and more resumes are marked "Needs a quick check".</div>
    </div>
    <div class="card"><h3>Application inbox — auto “Applied” detection</h3>
      <div class="muted" style="margin-bottom:8px">Applications happen on the portals' own sites, so the only trace is the confirmation email. Connect the inbox those confirmations land in and BenchPilot checks it every 15 minutes: when a Dice / Indeed / LinkedIn / ATS confirmation matches exactly one Queued card, that card flips to <b>Applied</b> by itself. Ambiguous matches are logged in Activity, never guessed. Read-only — mail is never moved, deleted or stored.</div>
      <label class="toggle"><input type="checkbox" id="s-imap-on"${s.imap_enabled === "1" ? " checked" : ""}> Watch this inbox for application confirmations</label>
      <div class="kv" style="margin-top:8px">
        <label>IMAP host</label><input type="text" id="s-imap-host" value="${esc(s.imap_host || "")}" placeholder="imap.gmail.com">
        <label>Inbox email</label><input type="text" id="s-imap-user" value="${esc(s.imap_user || "")}" placeholder="you@company.com">
        <label>App password</label><input type="password" id="s-imap-pass" value="${esc(s.imap_pass || "")}" placeholder="${s.imap_pass ? "saved (hidden)" : "Gmail: use an App Password, not your login password"}">
      </div>
      <div class="row" style="margin-top:8px"><button class="btn" id="s-imap-test">Test connection</button><span class="muted" id="s-imap-res"></span></div>
      <div class="muted" style="margin-top:6px">${s.imap_last_check ? `Last checked ${esc(s.imap_last_check)}.` : "Not checked yet."}${s.imap_last_error ? ` Last error: ${esc(s.imap_last_error)}` : ""}</div>
    </div>
    <div class="card"><h3>Data backup</h3>
      <div id="s-backup"><span class="muted">Loading…</span></div>
    </div>
    <div class="card"><h3>Fully automatic mode</h3>
      <label class="toggle"><input type="checkbox" id="s-autoq"${s.auto_queries === "0" ? "" : " checked"}> Search for the jobs the resumes are for (role + city, and Remote) — no typing needed</label>
      <label class="toggle"><input type="checkbox" id="s-autolearn"${s.auto_learn_skills === "0" ? "" : " checked"}> Learn new skills from resumes by itself</label>
      <div class="kv" style="margin-top:8px">
        <label>Max searches per run</label><input type="number" id="s-maxq" min="1" max="12" value="${esc(s.max_queries || 8)}">
        <label>Adzuna calls per day</label><input type="number" id="s-adzbud" min="0" max="240" value="${esc(s.adzuna_daily_budget || 80)}">
      </div>
      <div class="muted">Free Adzuna keys allow 250 calls a day and 2,500 a month. BenchPilot stays under the daily number above and slows its schedule down if needed.</div>
      <div id="s-auto" style="margin-top:10px"><span class="muted">Loading…</span></div>
    </div>
    <div class="card"><h3>Search queries</h3>
      <div class="muted" style="margin-bottom:6px">Extra searches you want on top of the automatic ones (used to fill any free search slots).</div>
      <div id="s-queries"></div>
      <button class="btn" id="s-qadd">Add query</button></div>
    <div class="card"><h3>Enabled sources</h3>
      ${srcs.filter((x) => x.name !== "urlimport").map((x) => `
        <label class="toggle"><input type="checkbox" data-src="${x.name}"${x.selected ? " checked" : ""}> ${esc(x.label)}</label>`).join("")}
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
      <div class="muted">BenchPilot re-pulls every enabled source on this schedule and re-matches consultants automatically — new postings land in the job board on their own. With Adzuna keys it automatically slows down if needed to stay inside the free daily limit.</div>
    </div>
    <div class="card"><h3>Match threshold</h3>
      <div class="row"><input type="range" id="s-thr" min="0" max="100" value="${esc(s.match_threshold || 60)}">
      <b id="s-thrv">${esc(s.match_threshold || 60)}</b></div>
      <div class="muted">Only matches scoring at/above this are created.</div></div>
    <div class="row"><button class="btn primary" id="s-save">Save settings</button>
      <span class="muted" id="s-msg"></span></div>`;

  $("#s-portcheck").onclick = async () => {
    const box = $("#s-portres");
    box.innerHTML = `<span class="muted">Checking… (up to ~30 seconds)</span>`;
    try {
      const rows = await api("/api/portals/check");
      box.innerHTML = rows.map((r) => {
        const dot = r.state === "reachable" ? "ok" : r.state.startsWith("up,") ? "off" : "err";
        return `<div class="srcstat"><span class="dot ${dot}"></span><b>${esc(r.label)}</b>
          <span class="muted">${esc(r.state)}${r.http_status ? " (HTTP " + r.http_status + ")" : ""}</span></div>`;
      }).join("");
    } catch (e) { box.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; }
  };
  (async () => {
    const box = $("#s-auto");
    try {
      const [st, ls] = await Promise.all([api("/api/collect/status"), api("/api/learned-skills")]);
      const qs = (st.queries || []).map((q) => `${esc(q.title)}${q.location ? " — " + esc(q.location) : ""}`);
      box.innerHTML = `
        <div><b>Searching now for:</b> ${qs.length ? qs.map((x) => `<span class="badge">${x}</span>`).join(" ") : '<span class="muted">nothing yet — upload a resume</span>'}</div>
        <div style="margin-top:6px"><b>Refresh every:</b> ${st.interval_minutes > 0 ? st.interval_minutes + " min" : "off"}${st.interval_wanted && st.interval_minutes > st.interval_wanted ? ` <span class="muted">(slowed down from ${st.interval_wanted} min to stay inside the Adzuna daily limit)</span>` : ""}
          · <b>Adzuna calls today:</b> ${st.adzuna_used_today} / ${st.adzuna_daily_budget}
          · <b>JSearch (LinkedIn/Indeed) calls:</b> today ${st.jsearch_used_today ?? 0} / ${esc(st.jsearch_daily_budget || "6")}, this month ${st.jsearch_used_month ?? 0} / ${esc(st.jsearch_monthly_limit || "200")}</div>
        <div style="margin-top:6px"><b>Skills learned from resumes (${ls.length}):</b>
          ${ls.length ? ls.map((x) => `<span class="badge">${esc(x.skill)} <a href="#" data-unlearn="${esc(x.skill)}" title="Remove this skill">x</a></span>`).join(" ") : '<span class="muted">none yet</span>'}</div>`;
      $$("#s-auto [data-unlearn]").forEach((a) => a.onclick = async (e) => {
        e.preventDefault();
        await api("/api/learned-skills/" + encodeURIComponent(a.dataset.unlearn), {method: "DELETE"});
        renderSettings();
      });
    } catch (e) { box.innerHTML = `<span class="muted">Status unavailable</span>`; }
  })();
  const loadBackup = async () => {
    const box = $("#s-backup");
    if (!box) return;
    try {
      const b = await api("/api/backup/status");
      box.innerHTML = b.enabled
        ? `<div><span class="dot ok"></span> <b>Backup is ON.</b> ${b.last_backup_at ? "Last saved " + esc(ago(b.last_backup_at)) + "." : "First save is coming within a minute."}
            ${b.restored ? '<span class="muted">(your data was brought back after the last restart)</span>' : ""}</div>
           ${b.last_error ? `<div class="errbox" style="margin-top:6px">${esc(b.last_error)}</div>` : ""}
           <button class="btn" id="s-bknow" style="margin-top:8px">Back up now</button>
           <div class="muted" style="margin-top:6px">Consultants, resumes, matches and keys are copied to permanent storage, so Republish does not delete them.</div>`
        : `<div><span class="dot err"></span> <b>Backup is OFF.</b> ${esc(b.reason || "")}</div>
           <div class="muted" style="margin-top:6px">Until it is ON, Republish deletes consultants, resumes and keys. See RUNBOOK.md, "Keep the data safe".</div>`;
      const btn = $("#s-bknow");
      if (btn) btn.onclick = async () => {
        btn.disabled = true; btn.textContent = "Saving…";
        try { await api("/api/backup/now", {method: "POST"}); toast("Backed up", "ok"); } catch (e) { toast(e.message, "err"); }
        loadBackup();
      };
    } catch (e) { box.innerHTML = `<span class="muted">Status unavailable</span>`; }
  };
  loadBackup();
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
  $("#s-imap-test").onclick = async () => {
    const res = $("#s-imap-res");
    res.textContent = "connecting…";
    try {
      const r = await api("/api/settings/imap-test", {method: "POST",
        body: JSON.stringify({host: $("#s-imap-host").value.trim(),
          user: $("#s-imap-user").value.trim(), pass: $("#s-imap-pass").value})});
      res.textContent = r.ok ? "Connected — inbox reachable." : "Failed: " + r.message;
    } catch (e) { res.textContent = "Failed: " + e.message; }
  };
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
      tailor_cutoff: $("#s-tcut").value.trim() || "65",
      tailor_max_per_run: $("#s-tmax").value.trim() || "10",
      search_queries: qs,
      enabled_sources: $$("[data-src]").filter((c) => c.checked).map((c) => c.dataset.src),
      match_threshold: $("#s-thr").value,
      collect_interval_minutes: $("#s-interval").value,
      usa_only: $("#s-usa").checked ? "1" : "0",
      auto_queries: $("#s-autoq").checked ? "1" : "0",
      auto_learn_skills: $("#s-autolearn").checked ? "1" : "0",
      max_queries: String(Math.max(1, Math.min(12, parseInt($("#s-maxq").value, 10) || 8))),
      adzuna_daily_budget: String(Math.max(0, Math.min(240, parseInt($("#s-adzbud").value, 10) || 0))),
      collect_emp_types: readEmp($("#s-emp"), "data-semp").join(","),
      imap_enabled: $("#s-imap-on").checked ? "1" : "0",
      imap_host: $("#s-imap-host").value.trim(),
      imap_user: $("#s-imap-user").value.trim(),
      imap_pass: $("#s-imap-pass").value,
    };
    // don't overwrite saved keys with the masked echo
    for (const k of ["adzuna_app_key", "rapidapi_key", "llm_api_key", "imap_pass"])
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
    <div class="card"><h3>Matches by consultant</h3><div id="ov-byc" class="muted">Loading…</div></div>
    <div class="card"><div class="row spread"><h3 style="margin:0">Company job boards</h3><span class="muted" id="ov-boards-n"></span></div>
      <div class="muted" style="margin:6px 0 10px">The staffing boards this team works (Vijay's list, added Nov 3). Many of these firms' postings already reach the pool through Dice, Adzuna and the other sources — this is the full directory, one click to each board.</div>
      <input type="text" id="ov-boards-q" placeholder="Search boards…" style="width:100%;margin-bottom:10px">
      <div id="ov-boards" class="muted">Loading…</div></div>
    <div class="card"><div class="row spread"><h3 style="margin:0">Top matches</h3>
      <button class="btn" id="ov-allm">View all</button></div>
      <div id="ov-top" style="margin-top:6px">${skelRows(3)}</div></div>
    <div class="card" id="ov-attn-card" style="display:none"><h3>Needs attention</h3><div id="ov-attn"></div></div>`;
  $("#ov-refresh").onclick = () => { renderOverview(); refreshBadges(); };
  $("#ov-allm").onclick = () => go("matches");
  $("#ov-collect").onclick = async () => { await runCollection(); renderOverview(); refreshBadges(); };
  try {
    const [cs, jobs, ms, apps, st, srcst, boardsRes] = await Promise.all([
      api("/api/consultants"), api("/api/jobs/count"),
      api("/api/matches/summary"), api("/api/applications"),
      api("/api/collect/status").catch(() => null),
      api("/api/sources/status").catch(() => null),
      api("/api/job-boards").catch(() => null),
    ]);
    const placed = apps.filter((a) => a.status === "placed").length;
    const active = apps.filter((a) => !["rejected", "withdrawn", "placed"].includes(a.status)).length;
    const noResume = cs.filter((c) => !c.has_resume);
    $("#ov-stats").innerHTML = [
      ["Consultants", cs.length, "", "consultants"],
      ["Jobs collected", jobs.count, "accent", "jobs"],
      ["Matches", ms.total, "accent", "matches"],
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
    if (srcst) {
      const bad = srcst.filter((s) => s.last_run && String(s.last_run.status || "").startsWith("error"));
      const ran = srcst.filter((s) => s.last_run && s.last_run.at);
      const okN = ran.length - bad.length;
      f.innerHTML += `<div style="margin-top:8px">Job sources: <b>${okN}/${ran.length} healthy</b>${bad.length ? ` — <span style="color:#d64545">${bad.map((s) => esc(s.name)).join(", ")} errored on the last run</span>` : " — every source pulled jobs on the last run"}</div>`;
    }
    const boards = (boardsRes && boardsRes.boards) || [];
    const drawBoards = (q) => {
      const list = boards.filter((b) => !q || b.name.toLowerCase().includes(q.toLowerCase()));
      $("#ov-boards-n").textContent = boards.length ? `${boards.length} boards` : "";
      $("#ov-boards").innerHTML = list.length ? `<div class="chiprow">${list.map((b) => b.url
        ? `<a class="chip" href="${esc(b.url)}" target="_blank" rel="noopener" style="text-decoration:none">${esc(b.name)} ↗</a>`
        : `<span class="chip miss">${esc(b.name)}</span>`).join("")}</div>`
        : "No boards match that search.";
    };
    drawBoards("");
    const bq = $("#ov-boards-q");
    if (bq) bq.oninput = () => drawBoards(bq.value.trim());
    const byc = {};
    (ms.by_consultant || []).forEach((r) => { byc[r.name] = r.n; });
    const maxByc = Math.max(1, ...Object.values(byc));
    $("#ov-byc").innerHTML = cs.length ? cs.map((c) => `
      <div class="frow" style="grid-template-columns:190px 1fr 44px"><span class="fl" style="white-space:normal">${esc(c.name)}</span>
        <div class="fbar"><div style="width:${Math.round(((byc[c.name] || 0) / maxByc) * 100)}%"></div></div>
        <span class="fn">${byc[c.name] || 0}</span></div>`).join("")
      : "No consultants yet.";
    const top = ms.top.slice(0, 5);
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


/* ================= FEEDBACK ================= */
const FB_CATS = {feature: "Feature request", problem: "Problem", idea: "Idea"};
const FB_STATUS = {new: "New", planned: "Planned", done: "Done", dismissed: "Dismissed"};
async function renderFeedback() {
  const el = $("#tab-feedback");
  if (!ME) await loadMe();
  const isAdmin = !ME || ME.is_admin !== false;
  let items = [];
  if (isAdmin) {
    try { items = await api("/api/feedback"); } catch (e) { /* list is best-effort */ }
  }
  el.innerHTML = `
    <div class="row spread"><h2>Feedback</h2></div>
    <div class="card">
      <h3 style="margin-top:0">What should this app do for you?</h3>
      <div class="muted" style="margin-bottom:8px">Tell the team what's missing, what's slow, or what you wish BenchPilot did. Points go to the workspace admins, who work through them and make the fixes.</div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        <select id="fb-cat" class="input">
          <option value="feature">Feature request</option>
          <option value="problem">Problem</option>
          <option value="idea" selected>Idea</option>
        </select>
        <input type="text" id="fb-name" class="input" placeholder="Your name (optional)" style="max-width:220px">
      </div>
      <textarea id="fb-text" class="input" rows="3" style="width:100%;margin-top:8px" placeholder="e.g. On Matches, let me filter by salary range…"></textarea>
      <div style="margin-top:8px"><button class="btn primary" id="fb-send">Send feedback</button></div>
    </div>
    ${isAdmin ? `<div id="fb-list">${items.length ? items.map((f) => `
      <div class="card">
        <div class="row spread">
          <div><span class="fb-chip fb-cat">${esc(FB_CATS[f.category] || "Idea")}</span>
            <span class="fb-chip fb-${esc(f.status)}">${esc(FB_STATUS[f.status] || f.status)}</span>
            <span class="muted">${esc(f.author || "Team member")} · ${esc(ago(f.created_at))}</span></div>
          <div class="row" style="gap:6px">${["planned", "done", "dismissed"].filter((st) => st !== f.status).map((st) => `<button class="btn" data-fb-status="${f.id}:${st}">${st === "dismissed" ? "Dismiss" : "Mark " + st}</button>`).join("")}</div>
        </div>
        <div style="margin-top:6px">${esc(f.text)}</div>
      </div>`).join("") : `<div class="card muted">No feedback yet — be the first to ask for something.</div>`}</div>` : `<div class="card muted">Only workspace admins see the feedback board — your points go straight to them.</div>`}`;
  $("#fb-send").onclick = async () => {
    const text = $("#fb-text").value.trim();
    if (!text) { toast("Write the feedback first", "err"); return; }
    try {
      await api("/api/feedback", {method: "POST", body: JSON.stringify({
        text, category: $("#fb-cat").value, name: $("#fb-name").value.trim()})});
      toast("Feedback sent — thank you", "ok");
      renderFeedback(); refreshBadges();
    } catch (e) { toast("Couldn't send: " + e.message, "err"); }
  };
  $$("[data-fb-status]", el).forEach((b) => b.onclick = async () => {
    const [fid, st] = b.dataset.fbStatus.split(":");
    try {
      await api(`/api/feedback/${fid}/status`, {method: "POST", body: JSON.stringify({status: st})});
      renderFeedback(); refreshBadges();
    } catch (e) { toast("Couldn't update: " + e.message, "err"); }
  });
}

/* ================= AGENT OFFICE ================= */
const AGENT_INFO = {
  scout: {name: "Scout", desc: "Watches the board for fresh matches above your threshold, grouped per consultant."},
  tailor: {name: "Tailor", desc: "Pre-drafts tailored resumes for good matches (score set in Settings, default 65+). Open a draft from Matches → Tailor resume, or from the Apply Queue's Resume button. Drafts only — added skills need a person to confirm them before anything is queued."},
  watchdog: {name: "Watchdog", desc: "Flags pipeline going cold and re-checks queued postings' links — a card whose posting has closed gets flagged before it wastes a morning. On autopilot it also leaves follow-up reminders on stale applications."},
  market_analyst: {name: "Market Analyst", desc: "Per-consultant demand briefing from live postings. On autopilot it adds search queries for hot skills the bench doesn't cover."},
  tracker: {name: "Application Tracker", desc: "Owns the post-apply pipeline: funnel counts, what moved since the last run (including Applied flips detected from confirmation emails), and cards stuck in screening or interview."},
  compliance: {name: "Compliance", desc: "Flags employment-type and visa/work-auth conflicts before you apply. On autopilot it quarantines employment-type mismatches — reversible from here. Visa conflicts are flagged, never auto-hidden."},
};
async function renderOffice() {
  const el = $("#tab-office");
  el.innerHTML = `
    <div class="row spread"><div><h2 style="margin-bottom:2px">Agent Office</h2>
      <div class="muted">Six agents working your pipeline around the clock — the office re-runs automatically every 15 minutes. Each card below shows what that agent actually produced on its last run: real matches found, resumes drafted, follow-ups flagged. If a number is 0, the agent ran and found nothing to do.</div></div>
      <div class="row" style="gap:10px;align-items:center">
        <label class="muted" style="display:flex;align-items:center;gap:6px;cursor:pointer" title="When on, agents fix safe issues themselves (quarantine mismatches, expand search queries, leave follow-up reminders). They never send email, queue applications, or acknowledge resume skills.">
          <input type="checkbox" id="of-autopilot"> Autopilot</label>
        <button class="btn primary" id="of-run">Run the office now</button></div></div>
    <div class="stats" id="of-stats" style="margin-top:14px">${skelCards(6)}</div>
    <div class="dash-grid" id="of-agents">${skelCards(6)}</div>
    <div id="of-briefing">${skelRows(4)}</div>`;
  $("#of-autopilot").onchange = async (e) => {
    try {
      await api("/api/office/autopilot", {method: "POST", body: JSON.stringify({enabled: e.target.checked})});
      toast(e.target.checked ? "Autopilot on — agents will fix safe issues themselves" : "Autopilot off — agents will only report", "ok");
    } catch (err) { toast("Couldn't save autopilot setting: " + err.message, "err"); e.target.checked = !e.target.checked; }
  };
  $("#of-run").onclick = async () => {
    const b = $("#of-run");
    b.disabled = true; b.textContent = "Starting…";
    try {
      const r = await api("/api/office/run", {method: "POST"});
      toast(r && r.started === false
        ? "The office is already running — the briefing refreshes when it finishes"
        : "Office run started in the background — the briefing refreshes in a minute or two", "ok");
    } catch (e) { toast("Couldn't start the office: " + e.message, "err"); }
    b.disabled = false; b.textContent = "Run the office now";
    refreshBadges();
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
  const auto = br.autopilot !== false;
  $("#of-autopilot").checked = auto;
  const scout = A.scout || {new_matches: 0, by_consultant: {}};
  const tailor = A.tailor || {drafted: 0, drafts: []};
  const wd = A.watchdog || {stale: 0, items: []};
  const mkt = A.market_analyst || {consultants: [], top_skills: []};
  const trk = A.tracker || {pipeline: {}, moved: 0, moved_items: [], email_flips: 0, stuck: 0, items: []};
  const comp = A.compliance || {issues: 0, items: []};

  $("#of-stats").innerHTML = [
    ["New matches (24h)", scout.new_matches, "accent", "matches"],
    ["Resume drafts ready", tailor.drafted, tailor.drafted ? "good" : "", null],
    ["Cards moved (last run)", trk.moved, trk.moved ? "good" : "", "queue"],
    ["Compliance flags", comp.issues, comp.issues ? "accent" : "", null],
    ["Stale pipeline items", wd.stale, wd.stale ? "accent" : "", "queue"],
    ["Briefing from", ago(br.run_at), "", null],
  ].map(([l, n, cls, tab]) => `<div class="stat ${cls}"${tab ? ` data-goto="${tab}" role="button" tabindex="0"` : ""}>
      <div class="n">${esc(String(n))}</div><div class="l">${l}</div></div>`).join("");
  $$("#of-stats .stat[data-goto]").forEach((s) => {
    s.onclick = () => go(s.dataset.goto);
    s.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") go(s.dataset.goto); };
  });

  $("#of-agents").innerHTML = ["scout", "tailor", "watchdog", "market_analyst", "tracker", "compliance"].map((k) => {
    const info = AGENT_INFO[k];
    const res = k === "scout" ? `${scout.new_matches} new matches`
      : k === "tailor" ? `${tailor.drafted} drafts ready`
      : k === "watchdog" ? `${wd.stale} stale · ${wd.links_dead || 0} closed postings`
      : k === "market_analyst" ? `${mkt.consultants.length} consultants briefed`
      : k === "tracker" ? `${trk.moved} moved · ${trk.stuck} stuck`
      : `${comp.issues} issues flagged`;
    return `<div class="card"><h3>${info.name} ${auto ? `<span class="chip" title="Autopilot is on — this agent fixes safe issues itself">AUTO</span>` : ""}</h3>
      <div class="muted" style="margin-bottom:8px">${info.desc}</div>
      <div><b>${esc(res)}</b> <span class="muted">· last run ${esc(ago(br.run_at))}</span></div></div>`;
  }).join("");

  const acts = [];
  for (const k of ["scout", "tailor", "watchdog", "market_analyst", "tracker", "compliance"]) {
    for (const a of ((A[k] || {}).actions || [])) acts.push({agent: AGENT_INFO[k].name, text: a.text});
  }
  const secs = [];
  secs.push(`<div class="card"><h3>Agent actions <span class="muted" style="font-weight:normal">· what the agents fixed by themselves</span></h3>
    ${acts.length ? acts.map((a) => `
      <div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)">
        <span class="badge">${esc(a.agent)}</span><div>${esc(a.text)}</div></div>`).join("")
      : `<div class="muted" style="margin-top:8px">${auto
          ? "No autonomous fixes this run — everything the agents checked was already healthy."
          : "Autopilot is off — the agents reported their findings but changed nothing. Turn it on to let them fix safe issues."}</div>`}</div>`);
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
            ${d.potential_score && d.potential_score > d.score
              ? `<span class="chip good">${d.score} → ${d.potential_score} if confirmed: ${(d.missing || []).map(esc).join(", ")}</span>` : ""}
            ${(d.flagged || []).length
              ? `<span class="chip warn">needs review: ${d.flagged.map(esc).join(", ")}</span>`
              : `<span class="chip">no added skills</span>`}
          </div></div>
        <button class="btn" data-draftm="${d.match_id}">Review</button>
      </div>`).join("")
      : `<div class="muted">No new drafts — good matches already have tailored resumes, or none reached the Tailor score in Settings (default 65).</div>`}
    <div class="muted" style="margin-top:8px">Drafts are never queued automatically. Review flagged skills in the tailor view before queueing.</div></div>`);

  secs.push(`<div class="card"><h3>Market pulse <span class="muted" style="font-weight:normal">· last ${mkt.window_days || 30} days</span></h3>
    ${(mkt.top_skills || []).length ? `<div style="margin:6px 0"><span class="muted">Hottest skills overall: </span>${mkt.top_skills.slice(0, 8).map((s) => `<span class="chip">${esc(s.skill)} <span class="muted">${s.jobs}</span></span>`).join("")}</div>` : ""}
    ${(mkt.consultants || []).length ? mkt.consultants.map((c) => `
      <div style="margin-top:10px"><b>${esc(c.consultant_name)}</b>
        ${(c.hot_skills || []).length ? `<div style="margin-top:4px"><span class="muted">hot: </span>${c.hot_skills.map((s) => `<span class="chip">${esc(s.skill)} <span class="muted">${s.jobs}</span></span>`).join("")}</div>` : ""}
        ${(c.gaps || []).length ? `<div style="margin-top:4px"><span class="muted">gaps worth learning: </span>${c.gaps.map((s) => `<span class="chip miss">${esc(s.skill)} <span class="muted">${s.jobs}</span></span>`).join("")}</div>` : ""}
      </div>`).join("")
      : `<div class="muted" style="margin-top:8px">No resume data to analyze yet — upload consultant resumes first.</div>`}</div>`);

  const funnel = Object.entries(trk.pipeline || {});
  secs.push(`<div class="card"><h3>Application Tracker <span class="muted" style="font-weight:normal">· the post-apply pipeline</span></h3>
    ${funnel.length ? `<div style="margin:6px 0">${funnel.map(([st, n]) => `<span class="chip">${esc(st)}: <b>${n}</b></span>`).join("")}</div>` : `<div class="muted" style="margin-top:8px">No applications yet.</div>`}
    <div class="muted" style="margin-top:6px">${trk.moved} card(s) moved since the last run${trk.email_flips ? ` · ${trk.email_flips} flipped to Applied from confirmation emails` : ""}.</div>
    ${(trk.moved_items || []).length ? trk.moved_items.map((m) => `
      <div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)">
        <span class="badge">${esc(m.status)}</span>
        <div><b>${esc(m.job_title)}</b> <span class="muted">· ${esc(m.company)} · ${esc(m.consultant_name)}</span></div>
      </div>`).join("") : ""}
    ${(trk.items || []).length ? `<div style="margin-top:10px"><b>Stuck mid-stage</b></div>` + trk.items.map((m) => `
      <div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)">
        <span class="badge">${esc(m.status)}</span>
        <div><b>${esc(m.job_title)}</b> <span class="muted">· ${esc(m.company)} · ${esc(m.consultant_name)}</span>
          <div class="muted">${esc(m.note)}</div></div>
      </div>`).join("") : ""}
  </div>`);

  secs.push(`<div class="card"><h3>Compliance flags</h3>
    ${(comp.items || []).length ? comp.items.map((c) => `
      <div class="row spread" style="padding:8px 0;border-bottom:1px solid var(--line)">
        <div class="row" style="gap:8px"><span class="chip warn">${esc(c.issue)}</span>
        <div><b>${esc(c.job_title)}</b> <span class="muted">· ${esc(c.company)} · for ${esc(c.consultant_name)} · score ${c.score}</span>
          <div class="muted">${esc(c.detail)}</div>
          ${c.quarantined ? `<div class="muted" style="margin-top:2px">Quarantined by Compliance — hidden from new matches.</div>` : ""}</div></div>
        ${c.quarantined ? `<button class="btn" data-unquar="${c.match_id}">Restore</button>` : ""}
      </div>`).join("")
      : `<div class="muted" style="margin-top:8px">No conflicts — employment types line up on current matches.</div>`}</div>`);

  const wdItems = [...(wd.items || []), ...(wd.dead_items || [])];
  secs.push(`<div class="card"><div class="row spread"><h3 style="margin:0">Needs attention</h3>
    ${wdItems.length ? `<button class="btn" id="of-allq">Open queue</button>` : ""}</div>
    ${wdItems.length ? wdItems.map((w) => `
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
  $$("[data-copy-draft]", el).forEach((b) => b.onclick = async () => {
    const pre = document.getElementById("of-draft-" + b.dataset.copyDraft);
    const text = pre ? pre.textContent : "";
    try {
      await navigator.clipboard.writeText(text);
      toast("Draft copied — paste it into your email", "ok");
    } catch (e) {
      toast("Copy failed — select the preview text manually", "err");
    }
  });
  $$("[data-unquar]", el).forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      await api(`/api/matches/${b.dataset.unquar}/unquarantine`, {method: "POST"});
      toast("Match restored", "ok");
    } catch (e) { toast("Restore failed: " + e.message, "err"); }
    renderOffice(); refreshBadges();
  });
  $$("[data-draftm]", el).forEach((b) => b.onclick = () => tailorModal(Number(b.dataset.draftm)));
}


/* ---------- in-app assistant ---------- */
function initAssistant() {
  if (document.querySelector(".asst-btn")) return;
  const history = [];
  const btn = document.createElement("button");
  btn.className = "asst-btn";
  btn.textContent = "💬 Assistant";
  const panel = document.createElement("div");
  panel.className = "asst-panel";
  panel.innerHTML = `
    <div class="asst-head"><span>BenchPilot Assistant</span><button type="button" class="asst-close" aria-label="Close">✕</button></div>
    <div class="asst-msgs"></div>
    <div class="asst-chips">
      <button type="button" class="asst-chip">Show my top matches</button>
      <button type="button" class="asst-chip">What's in my apply queue?</button>
      <button type="button" class="asst-chip">Why is a match scored low?</button>
      <button type="button" class="asst-chip">How do I approve a signup?</button>
    </div>
    <form class="asst-form"><input type="text" placeholder="Ask about your bench…" autocomplete="off"><button type="submit">Send</button></form>`;
  document.body.appendChild(btn);
  document.body.appendChild(panel);
  const msgs = panel.querySelector(".asst-msgs");
  const input = panel.querySelector(".asst-form input");
  const sendBtn = panel.querySelector(".asst-form button");
  const add = (role, text) => {
    const d = document.createElement("div");
    d.className = "asst-msg " + role;
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  };
  let greeted = false;
  const toggle = (open) => {
    panel.classList.toggle("open", open);
    if (open && !greeted) {
      greeted = true;
      add("bot", "Hi — I can answer questions about this workspace: your consultants, top matches, the apply queue, and how BenchPilot works. Try one of the suggestions below.");
    }
    if (open) input.focus();
  };
  btn.onclick = () => toggle(!panel.classList.contains("open"));
  panel.querySelector(".asst-close").onclick = () => toggle(false);
  const send = async (text) => {
    const q = (text || "").trim();
    if (!q) return;
    add("user", q);
    input.value = "";
    sendBtn.disabled = true;
    try {
      const r = await api("/api/assistant/chat", {method: "POST",
        body: JSON.stringify({message: q, history})});
      add("bot", r.reply || "No answer came back — try again.");
      history.push({role: "user", content: q}, {role: "assistant", content: r.reply || ""});
      if (history.length > 16) history.splice(0, history.length - 16);
    } catch (e) {
      add("bot", "Couldn't reach the assistant just now — try again in a moment.");
    }
    sendBtn.disabled = false;
    input.focus();
  };
  panel.querySelector(".asst-form").onsubmit = (e) => { e.preventDefault(); send(input.value); };
  panel.querySelectorAll(".asst-chip").forEach((c) => c.onclick = () => send(c.textContent));
}

/* ---------- router ---------- */
function render(tab) {
  ({overview: renderOverview, consultants: renderConsultants, jobs: renderJobs, matches: renderMatches,
    queue: renderQueue, office: renderOffice, feedback: renderFeedback, settings: renderSettings})[tab]();
}
initTheme();
render("overview");
refreshBadges();
initAssistant();
