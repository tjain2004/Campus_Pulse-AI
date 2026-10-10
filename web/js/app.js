// CampusPulse AI dashboard (vanilla JS, hash routing).
const main = document.getElementById("main");
const state = { me: null, chat: [], waTimer: null, bgTimer: null, waDirty: false, waGroupsKey: "" };

// ------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);
function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
  document.body.appendChild(t); setTimeout(() => t.remove(), 2600);
}
function fmtTs(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}
function nowRef() { return state.me && state.me.now ? new Date(state.me.now) : new Date(); }
function relative(iso) {
  if (!iso) return "";
  const h = (new Date(iso) - nowRef()) / 36e5;
  if (h < 0) return "passed";
  if (h < 1) return "within the hour";
  if (h < 24) return `in ${Math.round(h)}h`;
  const days = Math.round(h / 24);
  return days === 1 ? "tomorrow" : `in ${days} days`;
}
function soon(iso) { if (!iso) return false; const h = (new Date(iso) - nowRef()) / 36e5; return h >= 0 && h <= 48; }
function md(text) {
  // minimal, safe markdown: escape first, then **bold**, _italic_, "- " lists
  const lines = esc(text).split("\n");
  let html = "", inList = false;
  for (const raw of lines) {
    let l = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|\s)_(.+?)_(?=\s|$|[.,)])/g, "$1<em>$2</em>");
    if (/^\s*-\s+/.test(l)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${l.replace(/^\s*-\s+/, "")}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (l.trim()) html += `<p>${l}</p>`;
    }
  }
  return html + (inList ? "</ul>" : "");
}
const OFFICIAL = /\b(prof|dr|hod|dean|faculty|coordinator|tpo|placement cell|mentor|sir|ma'?am|principal)\b/i;
function bubble(sender, group, ts, text, extra = "") {
  const official = OFFICIAL.test(sender || "");
  return `<div class="bubble ${official ? "official" : ""}"><div class="who"><span>${esc(sender || "System")}</span>` +
    `<em>${esc(group || "")}</em></div><div class="txt">${esc(text)}</div><div class="meta">${esc(fmtTs(ts))}${extra}</div></div>`;
}
const CAT = { academics: "Academics", placements: "Placements", hackathons: "Hackathons", events: "Events",
              resources: "Resources", faculty: "Faculty", general: "General" };
function trustTag(label) {
  return ({ verified: '<span class="tag ok">Verified</span>', unverified: '<span class="tag warn">Unverified</span>',
            contradicted: '<span class="tag bad">Contradicted</span>' })[label] || "";
}
function emptyState(text, actionsHtml = "") { return `<div class="empty">${text}${actionsHtml ? `<div class="row">${actionsHtml}</div>` : ""}</div>`; }
function head(title, sub) { return `<header class="page-head"><h1>${title}</h1>${sub ? `<p class="muted">${sub}</p>` : ""}</header>`; }
async function busy(btn, fn) {
  const label = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> ${btn.dataset.busy || "Working"}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = label; }
}
function fail(e) { main.insertAdjacentHTML("afterbegin", `<div class="notice error" role="alert">${esc(e.message)}</div>`); }

// ---------------------------------------------------------------- pages
const pages = {};

pages.today = async () => {
  const d = await API.get("/api/dashboard");
  const name = (d.user.name || "there").split(" ")[0];
  const hr = nowRef().getHours();
  const greet = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  const m = d.metrics;
  const dateStr = nowRef().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
  if (!m.messages) {
    main.innerHTML = `<div class="today-head">${head(`${greet}, ${esc(name)}`, dateStr)}</div>` + emptyState(
      "No groups yet. Link your WhatsApp number to read your groups live, upload chat exports, or try the demo data.",
      `<a class="btn" href="#whatsapp">Link WhatsApp</a><a class="btn ghost" href="#import">Upload chat exports</a>
       <button class="btn ghost" id="demo-btn" data-busy="Loading demo">Load demo data</button>`);
    $("#demo-btn").onclick = (e) => busy(e.target, async () => { await API.post("/api/import/demo"); await refreshMe(); route(); });
    return;
  }
  const urgent = d.top.filter((i) => i.priority >= 80), upcoming = d.top.filter((i) => i.priority >= 55 && i.priority < 80);
  const fyi = d.top.filter((i) => i.priority < 55);
  main.innerHTML = `
    <div class="today-head">${head(`${greet}, ${esc(name)}`, `${dateStr}. ${m.messages} messages from ${m.groups} groups, read for you.`)}</div>
    <div class="kpis">
      <div class="kpi lead"><b>${m.attention}</b><span>need your attention</span></div>
      <div class="kpi"><b>${m.open_tasks}</b><span>open tasks</span></div>
      <div class="kpi"><b>${m.changes}</b><span>changes caught</span></div>
      <div class="kpi"><b>${m.noise_pct}%</b><span>noise filtered out</span></div>
    </div>
    <div class="today-grid"><div class="feed">
    ${m.conflicts ? `<div class="notice warn">${m.conflicts} announcement${m.conflicts > 1 ? "s give" : " gives"} conflicting details. <a href="#changes">Check what changed</a>.</div>` : ""}
    ${m.rumors ? `<div class="notice info">Rumor Shield kept ${m.rumors} unverified claim${m.rumors > 1 ? "s" : ""} out of this list. <a href="#rumors">See the verdicts</a>.</div>` : ""}
    <div class="section-title"><h2>Act on these first</h2><span class="n">${urgent.length}</span></div>
    ${urgent.map((i) => noticeItem(i)).join("") || emptyState("Nothing urgent. Enjoy the breathing room.")}
    <div class="section-title"><h2>Coming up</h2><span class="n">${upcoming.length}</span></div>
    ${upcoming.map((i) => noticeItem(i)).join("") || emptyState("Nothing else scheduled yet.")}
    ${fyi.length ? `<details class="fold"><summary>For your information (${fyi.length})</summary>${fyi.map((i) => noticeItem(i)).join("")}</details>` : ""}
    ${d.not_for_you.length ? `<details class="fold"><summary>Filtered out for your profile (${d.not_for_you.length})</summary>
      <p class="small muted">Nothing is hidden for good. Wrong call? Update your <a href="#profile">profile</a>.</p>
      ${d.not_for_you.map((i) => noticeItem(i, true)).join("")}</details>` : ""}
    </div><aside class="rail-col" id="today-rail" aria-label="At a glance"></aside></div>`;
  renderRail(m);
};

async function renderRail(m) {
  const rail = $("#today-rail"); if (!rail) return;
  let dl = { events: [], radar: { series: [], crunch_days: [] } };
  try { dl = await API.get("/api/deadlines"); } catch (e) { /* rail is optional */ }
  const week = dl.events.filter((e) => e.hours_left <= 24 * 7 && e.for_you !== false).slice(0, 6);
  const max = Math.max(2.5, ...dl.radar.series.map((s) => s.load));
  const wa = state.me.whatsapp || {};
  const waOn = wa.alive && wa.state === "ready";
  rail.innerHTML = `
    <section class="panel"><div class="panel-head"><h2>Next 7 days</h2><a href="#deadlines">All</a></div>
      ${week.length ? `<ul class="timeline">${week.map((e) => {
        const d = new Date(e.current_at);
        return `<li><div class="date ${e.hours_left <= 48 ? "soon" : ""}"><b>${d.getDate()}</b><span>${esc(d.toLocaleDateString("en-IN", { weekday: "short" }))}</span></div>
          <div><div class="t">${esc(e.title)}</div><div class="s">${esc(d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }))}${e.current_location ? ", " + esc(e.current_location) : ""}${e.status === "changed" ? ", updated" : ""}</div></div></li>`;
      }).join("")}</ul>` : '<p class="muted small">Nothing scheduled this week.</p>'}</section>
    <section class="panel"><div class="panel-head"><h2>Workload</h2><a href="#deadlines">Plan</a></div>
      <div class="radar mini" role="img" aria-label="Workload for the next 14 days">${dl.radar.series.map((s) => {
        const dt = new Date(s.date + "T00:00");
        return `<div class="day" title="${esc(dt.toDateString())}: ${esc(s.items.join(", ") || "free")}"><div class="bar ${s.load >= 2 ? "crunch" : ""}" style="height:${(s.load / max) * 100}%"></div><span class="lbl">${dt.getDate()}</span></div>`;
      }).join("")}</div>
      <p class="small muted" style="margin:.5rem 0 0">${dl.radar.crunch_days.length ? `Crunch on ${dl.radar.crunch_days.length} day${dl.radar.crunch_days.length > 1 ? "s" : ""}: highlighted in yellow.` : "No crunch in the next two weeks."}</p></section>
    <section class="panel"><div class="panel-head"><h2>Trust check</h2><a href="#rumors">Details</a></div>
      <dl class="kv"><dt>Rumours kept out</dt><dd>${m.rumors}</dd><dt>Conflicts to verify</dt><dd>${m.conflicts}</dd><dt>Changes applied</dt><dd>${m.changes}</dd></dl></section>
    <section class="panel"><div class="panel-head"><h2>WhatsApp</h2><a href="#whatsapp">${waOn ? "Manage" : "Link"}</a></div>
      <p class="small" style="margin:0"><span class="dot ${waOn ? "on" : ""}"></span> ${waOn ? "Connected. New messages arrive every 20 seconds." : "Not connected. Link your number to read groups live."}</p></section>`;
}

function noticeItem(i, filtered = false) {
  let cls = i.band === "urgent" ? "urgent" : "";
  const tags = [];
  if (i.status === "changed") { cls = "updated"; tags.push('<span class="tag upd">Updated</span>'); }
  if (i.status === "conflict") { cls = "conflict"; tags.push('<span class="tag warn">Conflicting info</span>'); }
  if (i.status === "cancelled") tags.push('<span class="tag bad">Cancelled</span>');
  if (i.relevance === "relevant") tags.push('<span class="tag you">For you</span>');
  if (i.needs_verification) tags.push('<span class="tag warn">Check the date</span>');
  tags.push(trustTag(i.trust_label));
  tags.push(`<span class="tag">${esc(CAT[i.category] || i.category)}</span>`);
  const due = i.type === "deadline" || i.type === "task";
  const whenTxt = i.when_label ? `${due ? "Due " : ""}${esc(i.when_label)}` : "";
  const rel = i.when ? relative(i.when) : "";
  const whenHtml = whenTxt ? `<span class="ico"><svg class="i"><use href="#i-clock"/></svg>${whenTxt} ${rel ? (soon(i.when) ? `<span class="hl">${esc(rel)}</span>` : `(${esc(rel)})`) : ""}</span>` : "";
  const why = filtered ? `Filtered because: ${esc(i.relevance_reason || "")}` : `Why it's here: ${esc(i.reason || "")}`;
  const also = i.also_in && i.also_in.length ? ` <span>also in ${esc(i.also_in.join(", "))}</span>` : "";
  return `<article class="notice-item ${cls}">
    <div class="n-top"><div><div class="n-title">${esc(i.title)}</div>
      <div class="n-when">${whenHtml}${i.location ? `<span class="ico"><svg class="i"><use href="#i-pin"/></svg>${esc(i.location)}</span>` : ""}</div></div>
      <div class="tags">${tags.join("")}</div></div>
    <div class="why">${why}</div>
    ${bubble(i.sender, i.group, i.timestamp, i.text, also)}
  </article>`;
}

pages.changes = async () => {
  const list = await API.get("/api/changes");
  const conflicts = list.filter((c) => c.kind === "conflict"), changes = list.filter((c) => c.kind === "change");
  const FIELD = { when: "Date and time", location: "Venue", status: "Status" };
  const diff = (c) => Object.keys(c.new_values).map((k) => `<div class="diff"><span class="field">${FIELD[k] || k}</span>
      <span class="old">${esc(c.old_values[k] || "Not stated")}</span><span class="arrow" aria-hidden="true">→</span>
      <span class="new">${esc(c.new_values[k])}</span></div>`).join("");
  const src = (m, label) => m ? `<p class="small muted" style="margin:.7rem 0 0">${label}</p>${bubble(m.sender, m.group, m.timestamp, m.text)}` : "";
  main.innerHTML = head("What changed", "When a newer message changes an earlier one, you see both side by side. A change is applied only when the new message says it is one; otherwise it's shown as a conflict for you to confirm.") +
    `<div class="section-title"><h2>Conflicts to confirm</h2><span class="n">${conflicts.length}</span></div>` +
    (conflicts.map((c) => `<article class="notice-item conflict"><div class="n-title">${esc(c.title)}</div>${diff(c)}
       <div class="why">${esc(c.explanation)}</div>${src(c.old_message, "Earlier message")}${src(c.new_message, "Newer message")}</article>`).join("")
      || emptyState("No conflicting announcements.")) +
    `<div class="section-title"><h2>Confirmed changes</h2><span class="n">${changes.length}</span></div>` +
    (changes.map((c) => `<article class="notice-item updated"><div class="n-title">${esc(c.title)}</div>${diff(c)}
       <div class="why">${esc(c.explanation)}</div>${src(c.old_message, "Original")}${src(c.new_message, "Update")}</article>`).join("")
      || emptyState("No changes detected yet."));
};

pages.rumors = async () => {
  const d = await API.get("/api/rumors");
  const busted = d.rumors.filter((r) => r.trust_label === "contradicted").length;
  main.innerHTML = head("Rumor Shield", "Every claim is checked against official senders (faculty, coordinators, mentors) in all your groups, and gets a verdict with evidence.") +
    `<div class="stats"><div class="stat"><b>${d.checked}</b><span>messages checked</span></div>
      <div class="stat"><b>${d.rumors.length}</b><span>rumours found</span></div>
      <div class="stat"><b>${busted}</b><span>contradicted by an official</span></div></div>
    <div class="section-title"><h2>Verdicts</h2></div>` +
    (d.rumors.map((r) => {
      const bad = r.trust_label === "contradicted";
      return `<article class="notice-item ${bad ? "contradicted" : "conflict"}">
        <div class="n-top"><div class="n-title">${bad ? "Contradicted: an official message says otherwise" : "Unverified: no official source confirms this"}</div>
          <div class="tags">${trustTag(r.trust_label)}<span class="tag">Trust ${r.trust_score}/100</span></div></div>
        <div class="meter"><i style="width:${Math.max(4, r.trust_score)}%;background:${bad ? "var(--bad)" : "var(--warn)"}"></i></div>
        ${bubble(r.sender, r.group_name, r.timestamp, r.text)}
        <div class="why">${r.trust_reasons.map(esc).join(". ")}.</div>
        ${r.evidence ? `<p class="small muted" style="margin:.7rem 0 0">Official evidence</p>${bubble(r.evidence.sender, r.evidence.group_name, r.evidence.timestamp, r.evidence.text)}` : ""}
      </article>`;
    }).join("") || emptyState("No rumours spotted. Your groups are behaving.")) +
    `<div class="section-title"><h2>Unanswered questions</h2><span class="n">${d.doubts.length}</span></div>
     <p class="muted small">Questions nobody answered in their own group, answered from your other groups and documents.</p>` +
    (d.doubts.map((q) => `<article class="notice-item ${q.found ? "verified" : ""}">
        <div class="n-top"><div class="n-title">${q.found ? `Answer found in ${esc(q.from.join(", "))}` : "Nobody has answered this anywhere yet"}</div>
          <div class="tags">${q.cross_group ? '<span class="tag upd">From another group</span>' : ""}</div></div>
        ${bubble(q.sender, q.group, q.timestamp, q.question)}
        ${q.found ? `<div class="msg-a" style="margin-top:.7rem;background:var(--paper)">${md(q.answer)}
          <ul class="sources">${q.sources.map((s, i) => `<li>[${i + 1}] ${esc(s)}</li>`).join("")}</ul></div>`
          : `<p class="why">Ask the organiser directly. CampusPulse will pick up the answer when it's posted.</p>`}
      </article>`).join("") || emptyState("Every question got an answer."));
};

pages.deadlines = async () => {
  const d = await API.get("/api/deadlines");
  const r = d.radar, max = Math.max(2.5, ...r.series.map((s) => s.load));
  const bars = r.series.map((s) => {
    const dt = new Date(s.date + "T00:00");
    const label = dt.toLocaleDateString("en-IN", { weekday: "short", day: "numeric" });
    return `<div class="day" title="${esc(label)}: ${esc(s.items.join(", ") || "free")}">
      <div class="bar ${s.load >= 2 ? "crunch" : ""}" style="height:${(s.load / max) * 100}%"></div><span class="lbl">${esc(label)}</span></div>`;
  }).join("");
  const crunch = r.crunch_days.map((x) => new Date(x + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }));
  main.innerHTML = head("Deadlines", "Everything with a date, with the latest details. Crunch Radar shows when deadlines pile up and when to start each task.") +
    `<div class="row" style="margin-bottom:1rem"><a class="btn ghost" href="/api/calendar.ics">Add all to my calendar</a>
      <span class="small muted">Works with Google Calendar, Outlook and Apple Calendar.</span></div>
    <div class="section-title"><h2>Crunch Radar, next 14 days</h2></div>
    <div class="radar" role="img" aria-label="Workload per day for the next 14 days">${bars}</div>
    ${crunch.length ? `<div class="notice warn">Deadlines stack up on ${esc(crunch.join(", "))}. Start early with the plan below.</div>` : `<p class="small muted" style="margin-top:.6rem">Your next two weeks look manageable.</p>`}
    ${r.plans.length ? `<h3 style="margin:1rem 0 .4rem">When to start</h3><ul class="plan">${r.plans.map((p) =>
      `<li>Start <strong>${esc(p.task)}</strong> by <strong>${esc(p.start_by)}</strong>, about ${p.effort_days} day${p.effort_days > 1 ? "s" : ""} of work, due ${esc(p.due)}</li>`).join("")}</ul>` : ""}
    <div class="section-title"><h2>Timeline</h2><span class="n">${d.events.length}</span></div>` +
    (d.events.map((e) => {
      const cls = e.status === "changed" ? "updated" : e.status === "conflict" ? "conflict" : e.hours_left <= 48 ? "urgent" : "";
      const rel = relative(e.current_at);
      return `<article class="notice-item ${cls}"><div class="n-top"><div>
          <div class="n-title">${esc(e.title)}</div>
          <div class="n-when"><span>${e.kind === "deadline" ? "Due " : ""}${esc(e.when_label)} ${soon(e.current_at) ? `<span class="hl">${esc(rel)}</span>` : `(${esc(rel)})`}</span>
            ${e.current_location ? `<span>${esc(e.current_location)}</span>` : ""}</div></div>
          <div class="tags">${e.kind === "deadline" ? '<span class="tag">Deadline</span>' : '<span class="tag">Event</span>'}
            ${e.status === "changed" ? '<span class="tag upd">Updated</span>' : ""}${e.status === "conflict" ? '<span class="tag warn">Confirm</span>' : ""}${e.for_you === false ? '<span class="tag">Not for you</span>' : ""}</div></div>
        ${e.status === "changed" ? `<div class="why">Originally <s>${esc(e.original_label)}${e.original_location ? ", " + esc(e.original_location) : ""}</s></div>` : ""}
        <div class="why">From ${esc(e.groups.join(", "))}, ${e.source_count} message${e.source_count > 1 ? "s" : ""}</div></article>`;
    }).join("") || emptyState("No upcoming deadlines or events."));
};

pages.tasks = async () => {
  const list = await API.get("/api/tasks");
  const pending = list.filter((t) => t.status === "pending"), done = list.filter((t) => t.status === "done");
  const pct = list.length ? Math.round((done.length / list.length) * 100) : 0;
  const item = (t) => `<div class="task ${t.status === "done" ? "done" : ""}">
      <input type="checkbox" data-id="${t.id}" ${t.status === "done" ? "checked" : ""} aria-label="Mark ${esc(t.title)} done">
      <div style="flex:1"><div class="n-title">${esc(t.title)}</div>
        ${t.due_label ? `<div class="n-when"><span>Due ${esc(t.due_label)} ${t.overdue ? '<span class="tag bad">Overdue</span>' : soon(t.deadline) ? `<span class="hl">${esc(relative(t.deadline))}</span>` : `(${esc(relative(t.deadline))})`}</span></div>` : ""}
        ${t.event_status === "changed" ? '<div class="notice info small">The deadline was updated by a newer message. The date above is the latest.</div>' : ""}
        ${t.event_status === "conflict" ? '<div class="notice warn small">Groups disagree about this deadline. <a href="#changes">Compare them</a>.</div>' : ""}
        ${t.status === "pending" ? bubble(t.source_sender, t.group_name, t.source_time, t.source_text) : ""}</div></div>`;
  main.innerHTML = head("My tasks", "Pulled from deadlines in your groups. If a deadline moves in any group, the date here moves with it.") +
    `<div class="progress" aria-label="${pct}% done"><i style="width:${pct}%"></i></div>
     <p class="small muted">${done.length} of ${list.length} done</p>
     ${pending.map(item).join("") || emptyState("All caught up.")}
     ${done.length ? `<details class="fold"><summary>Done (${done.length})</summary>${done.map(item).join("")}</details>` : ""}`;
  main.querySelectorAll("input[type=checkbox][data-id]").forEach((cb) => {
    cb.onchange = async () => {
      await API.patch(`/api/tasks/${cb.dataset.id}`, { status: cb.checked ? "done" : "pending" });
      toast(cb.checked ? "Marked done" : "Moved back to to-do");
      refreshMe(); pages.tasks();
    };
  });
};

pages.ask = async () => {
  const examples = ["What do we need to submit for SIH, and when is it due?", "Where is the fest briefing?",
    "When is the DBMS assignment due?", "Is the OS mid-sem postponed?", "How many members are allowed in an SIH team?"];
  const render = () => {
    $("#chat").innerHTML = state.chat.map((t) => t.q ? `<div class="msg-q">${esc(t.q)}</div>` :
      `<div class="msg-a">${t.loading ? '<span class="spinner"></span> Searching your groups' : md(t.answer)}
        ${(t.conflicts || []).map((c) => `<div class="notice warn small">${esc(c)}</div>`).join("")}
        ${t.citations && t.citations.length ? `<details class="sources"><summary>Sources (${t.citations.length})</summary><ol>
          ${t.citations.map((c) => `<li><strong>${esc(c.label)}</strong><br>${esc(c.excerpt)}</li>`).join("")}</ol></details>` : ""}</div>`).join("");
  };
  main.innerHTML = head("Ask Campus AI", `Answers come only from your groups and documents, with sources. ${state.me.llm ? "" : "Add an AI key in .env for more conversational answers."}`) +
    `<div class="chips">${examples.map((e) => `<button class="chip" type="button">${esc(e)}</button>`).join("")}</div>
     <div class="chat" id="chat" aria-live="polite"></div>
     <form class="ask-box" id="ask-form"><input id="ask-input" type="text" maxlength="500" placeholder="Ask about deadlines, venues, requirements…" aria-label="Your question">
       <button class="btn" type="submit">Ask</button></form>`;
  render();
  const ask = async (q) => {
    if (!q.trim()) return;
    state.chat.push({ q }); const a = { loading: true }; state.chat.push(a); render();
    try { Object.assign(a, await API.post("/api/ask", { question: q }), { loading: false }); }
    catch (e) { Object.assign(a, { loading: false, answer: e.message }); }
    render(); window.scrollTo(0, document.body.scrollHeight);
  };
  main.querySelectorAll(".chip").forEach((b) => (b.onclick = () => ask(b.textContent)));
  $("#ask-form").onsubmit = (e) => { e.preventDefault(); const i = $("#ask-input"); ask(i.value); i.value = ""; };
  $("#ask-input").focus();
};

pages.groups = async () => {
  const groups = await API.get("/api/groups");
  if (!groups.length) { main.innerHTML = head("Groups") + emptyState("No groups yet.", '<a class="btn" href="#whatsapp">Link WhatsApp</a><a class="btn ghost" href="#import">Upload chat exports</a>'); return; }
  const sel = { gid: "", type: "", noise: false };
  main.innerHTML = head("Groups", "The original messages, with what CampusPulse understood from each one.") +
    `<div class="pill-tabs" id="gtabs"><button aria-pressed="true" data-g="">All groups</button>
      ${groups.map((g) => `<button aria-pressed="false" data-g="${g.id}">${esc(g.name)} <span class="muted">${g.message_count}</span></button>`).join("")}</div>
     <div class="filters"><select id="ftype" aria-label="Message type"><option value="">All types</option>
       ${["deadline", "task", "update", "announcement", "question", "resource", "chatter"].map((t) => `<option>${t}</option>`).join("")}</select>
       <label class="row small"><input type="checkbox" id="fnoise"> Show noise (ok, thanks, emoji)</label>
       <button class="btn ghost small hidden" id="del-group">Delete this group's data</button></div>
     <div id="glist"></div>`;
  const load = async () => {
    const q = new URLSearchParams({ group_id: sel.gid, type: sel.type, noise: sel.noise ? "1" : "0" });
    const msgs = await API.get(`/api/messages?${q}`);
    $("#glist").innerHTML = msgs.map((m) => `<div style="margin-bottom:.4rem">
        ${bubble(m.sender, m.group, m.timestamp, m.text, "")}
        <div class="tags" style="justify-content:flex-start;margin:.3rem 0 .6rem">
          ${m.type ? `<span class="tag">${esc(m.type)}</span>` : ""}${m.is_noise ? '<span class="tag">noise</span>' : ""}
          ${trustTag(m.trust_label)}${m.relevance === "not_relevant" ? '<span class="tag">not for you</span>' : ""}
          ${m.links.map((u) => `<a class="tag upd" href="${esc(u)}" target="_blank" rel="noopener">open link</a>`).join("")}</div></div>`).join("")
      || emptyState("No messages match these filters.");
    $("#del-group").classList.toggle("hidden", !sel.gid);
  };
  $("#gtabs").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    main.querySelectorAll("#gtabs button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    sel.gid = b.dataset.g; load();
  };
  $("#ftype").onchange = (e) => { sel.type = e.target.value; load(); };
  $("#fnoise").onchange = (e) => { sel.noise = e.target.checked; load(); };
  $("#del-group").onclick = async () => {
    if (!confirm("Delete every imported message from this group? This can't be undone.")) return;
    await API.del(`/api/groups/${sel.gid}`); toast("Group data deleted"); pages.groups();
  };
  load();
};

pages.resources = async () => {
  const d = await API.get("/api/resources");
  main.innerHTML = head("Resources", "PDFs and links shared across your groups. PDF pages are searchable from Ask Campus AI.") +
    `<div class="section-title"><h2>Documents</h2><span class="n">${d.documents.length}</span></div>` +
    (d.documents.map((doc) => `<article class="notice-item verified"><div class="n-title">${esc(doc.filename)}</div>
       <div class="why">${doc.chunk_count} searchable sections${doc.group_name ? `, shared in ${esc(doc.group_name)}` : ""}</div>
       <div style="margin-top:.5rem">${md(doc.summary || "")}</div></article>`).join("") || emptyState("No PDFs yet.", '<a class="btn ghost" href="#import">Upload a PDF</a>')) +
    `<div class="section-title"><h2>Links and notes</h2><span class="n">${d.links.length}</span></div>` +
    (d.links.map((l) => bubble(l.sender, l.group_name, l.timestamp, l.text,
      l.links.map((u) => ` <a href="${esc(u)}" target="_blank" rel="noopener">open</a>`).join(""))).join("") || emptyState("No shared links yet."));
};

// ------------------------------------------------------------ whatsapp
pages.whatsapp = async () => {
  main.innerHTML = head("WhatsApp", "Link your number the same way WhatsApp Web works, then choose which groups CampusPulse may read. New messages arrive in your feed automatically.") +
    `<div class="wa-steps"><div id="wa-status" class="panel"><span class="spinner"></span> Checking connection…</div><div id="wa-groups"></div></div>`;
  state.waDirty = false; state.waGroupsKey = "";
  await waTick();
  state.waTimer = setInterval(waTick, 3000);
};

async function waTick() {
  if (location.hash !== "#whatsapp") return;
  let s;
  try { s = await API.get("/api/whatsapp/status"); } catch (e) { return; }
  const box = $("#wa-status"); if (!box) return;
  const st = s.alive ? s.state : (["logged_out", "auth_failure"].includes(s.state) ? s.state : "off");
  updateWaDot(st === "ready");
  const risk = `<div class="notice warn small">This uses an unofficial WhatsApp Web link, because WhatsApp's official API can't read groups you're already in.
    Automating WhatsApp Web is against WhatsApp's terms, so the number could be restricted. For demos, use a spare number that's in your groups.
    CampusPulse only reads the groups you tick, and never sends anything.</div>`;
  if (st === "off" || st === "logged_out" || st === "not_started") {
    box.innerHTML = `<h2>Link your WhatsApp number</h2>
      <p class="muted">You'll scan a QR code with your phone: WhatsApp, then Settings, then Linked devices, then Link a device.</p>${risk}
      ${s.requirements ? `<div class="notice info small">Before the first link, set up the bridge once on this computer:
        install Node.js 18 or newer from nodejs.org, then run <code>npm install</code> inside the <code>whatsapp_bridge</code> folder and restart <code>python app.py</code>.</div>` : ""}
      <div class="row"><button class="btn" id="wa-connect" data-busy="Starting" ${s.requirements ? "disabled" : ""}>Show QR code</button>
        <button class="btn ghost" id="wa-sim" data-busy="Starting">Try a simulated connection</button></div>
      ${st === "logged_out" ? '<p class="small muted" style="margin-top:.6rem">This number was unlinked.</p>' : ""}`;
    $("#wa-connect").onclick = (e) => busy(e.target, async () => { try { await API.post("/api/whatsapp/connect", {}); waTick(); } catch (err) { toast(err.message); } });
    $("#wa-sim").onclick = (e) => busy(e.target, async () => { await API.post("/api/whatsapp/connect", { simulate: true }); waTick(); });
    $("#wa-groups").innerHTML = "";
    return;
  }
  if (st === "qr") {
    box.innerHTML = `<h2>Scan to link your number</h2><div class="qr-wrap">
      <img src="/api/whatsapp/qr?t=${Date.now()}" alt="WhatsApp link QR code">
      <ol><li>Open WhatsApp on your phone</li><li>Go to Settings, then Linked devices</li><li>Tap Link a device and scan this code</li></ol></div>
      <p class="small muted">The code refreshes by itself about every 20 seconds.${s.simulated ? " This is a simulated connection: it links by itself in a few seconds." : ""}</p>
      <button class="btn ghost small" id="wa-cancel">Cancel</button>`;
    $("#wa-cancel").onclick = async () => { await API.post("/api/whatsapp/disconnect", {}); waTick(); };
    return;
  }
  if (st === "auth_failure") {
    box.innerHTML = `<h2>Couldn't log in to WhatsApp</h2><div class="notice error">${esc(s.detail || "")}</div>
      ${s.log ? `<pre class="log">${esc(s.log)}</pre>` : ""}<button class="btn" id="wa-retry">Try again</button>`;
    $("#wa-retry").onclick = async () => { await API.post("/api/whatsapp/connect", {}); waTick(); };
    return;
  }
  if (st !== "ready") {
    box.innerHTML = `<div class="wa-state"><span class="spinner"></span> ${esc(s.detail || "Connecting")}</div>`;
    return;
  }
  const a = s.account || {};
  const synced = s.synced && (s.synced.new || s.synced.documents)
    ? `<div class="notice ok small">Fetched ${s.synced.new} new message${s.synced.new === 1 ? "" : "s"}${s.synced.documents ? ` and ${s.synced.documents} PDF${s.synced.documents > 1 ? "s" : ""}` : ""}. Your feed is updated.</div>` : "";
  box.innerHTML = `<div class="profile-head" style="margin:0">
      <div class="avatar">${s.has_avatar ? `<img src="/api/whatsapp/avatar" alt="">` : esc((a.name || "?").charAt(0))}</div>
      <div><div class="wa-state"><span class="wa-dot on"></span>Connected${s.simulated ? " (simulated)" : ""}</div>
        <div><strong>${esc(a.name || "Your account")}</strong>, number ending ${esc((a.number || "").slice(-4))}</div>
        ${a.about ? `<div class="small muted">${esc(a.about)}</div>` : ""}
        <div class="small muted">${esc(s.detail || "")}</div></div></div>
    ${synced}
    <div class="row" style="margin-top:.8rem"><button class="btn ghost small" id="wa-stop">Disconnect</button>
      <button class="btn ghost small" id="wa-unlink">Unlink this number</button></div>`;
  $("#wa-stop").onclick = async () => { await API.post("/api/whatsapp/disconnect", {}); toast("Disconnected. Your login is kept for next time."); waTick(); };
  $("#wa-unlink").onclick = async () => {
    if (!confirm("Unlink this WhatsApp number? You'll need to scan a QR code again.")) return;
    await API.post("/api/whatsapp/disconnect", { logout: true }); toast("Number unlinked"); waTick();
  };
  if (s.synced && s.synced.new) refreshMe();
  renderWaGroups(s);
}

function renderWaGroups(s) {
  const key = JSON.stringify([s.groups.map((g) => g.id), s.selected]);
  if (state.waDirty || key === state.waGroupsKey) return;
  state.waGroupsKey = key;
  const sel = new Set(s.selected);
  $("#wa-groups").innerHTML = `<div class="panel"><h2>Choose groups to read</h2>
    <p class="muted small">Tick your class, placement, hackathon and club groups. Recent history (up to 300 messages each) is imported, then new messages stream in.</p>
    ${s.groups.length ? `<input type="text" id="wa-filter" placeholder="Search your groups" aria-label="Search groups">
      <div class="group-list" id="wa-glist">${s.groups.map((g) => `<label data-name="${esc(g.name.toLowerCase())}">
        <input type="checkbox" value="${esc(g.id)}" ${sel.has(g.id) ? "checked" : ""}>
        <span style="flex:1">${esc(g.name)}</span><span class="small muted">${g.participants} members</span></label>`).join("")}</div>
      <button class="btn" id="wa-save" data-busy="Saving">Save groups</button> <span class="small muted" id="wa-count">${sel.size} selected</span>`
      : '<p><span class="spinner"></span> Loading your groups…</p>'}</div>`;
  const list = $("#wa-glist"); if (!list) return;
  list.onchange = () => { state.waDirty = true; $("#wa-count").textContent = `${list.querySelectorAll("input:checked").length} selected`; };
  $("#wa-filter").oninput = (e) => {
    const q = e.target.value.toLowerCase();
    list.querySelectorAll("label").forEach((l) => l.classList.toggle("hidden", !l.dataset.name.includes(q)));
  };
  $("#wa-save").onclick = (e) => busy(e.target, async () => {
    const ids = [...list.querySelectorAll("input:checked")].map((i) => i.value);
    await API.put("/api/whatsapp/groups", { group_ids: ids });
    state.waDirty = false; state.waGroupsKey = "";
    toast(ids.length ? "Saved. Importing messages from your groups" : "Saved. No groups will be read");
  });
}

// --------------------------------------------------------------- import
pages.import = async () => {
  const groups = await API.get("/api/groups");
  main.innerHTML = head("Import chats", "No live link? Export a group from WhatsApp (open the group, then More, then Export chat, Without media) and upload the .txt file here.") +
    `<div class="wa-steps">
     <form class="panel" id="chat-form"><h2>WhatsApp chat exports</h2>
       <input type="file" id="chat-files" accept=".txt" multiple aria-label="Chat export files">
       <div id="chat-rows" style="margin-top:.8rem"></div>
       <button class="btn" type="submit" data-busy="Importing">Import and analyse</button><div id="chat-result"></div></form>
     <form class="panel" id="pdf-form"><h2>PDFs and circulars</h2>
       <div class="row"><input type="file" name="file" accept=".pdf" aria-label="PDF file" style="flex:1">
       <select name="group_id" aria-label="Shared in group" style="width:auto"><option value="">Not from a group</option>
         ${groups.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}</select></div>
       <button class="btn" type="submit" style="margin-top:.8rem" data-busy="Reading PDF">Import PDF</button><div id="pdf-result"></div></form>
     <div class="panel"><h2>Demo and your data</h2>
       <p class="muted small">The demo adds four sample groups and one PDF, and pins "today" to 10 Oct 2026 so the sample deadlines are upcoming. You can unpin it in your profile.</p>
       <div class="row"><button class="btn ghost" id="demo" data-busy="Loading">Load demo data</button>
         <button class="btn ghost" id="reproc" data-busy="Re-analysing">Re-analyse everything</button>
         <button class="btn danger" id="wipe">Delete all my imported data</button></div></div></div>`;
  const cats = ["general", "academics", "placements", "hackathons", "events", "resources", "faculty"];
  $("#chat-files").onchange = (e) => {
    $("#chat-rows").innerHTML = [...e.target.files].map((f) => `<div class="grid-3" style="margin-bottom:.6rem">
      <label class="field"><span>Group name</span><input type="text" name="names" value="${esc(f.name.replace(/\.txt$/i, "").replace(/WhatsApp Chat (with|-) /, "").replace(/_/g, " "))}"></label>
      <label class="field"><span>Type</span><select name="categories">${cats.map((c) => `<option>${c}</option>`).join("")}</select></label>
      <label class="field"><span>Official senders (optional)</span><input type="text" name="officials" placeholder="Prof. Rao, Placement Cell"></label></div>`).join("");
  };
  $("#chat-form").onsubmit = (e) => {
    e.preventDefault();
    const files = $("#chat-files").files;
    if (!files.length) { $("#chat-result").innerHTML = '<div class="notice error">Choose at least one .txt file.</div>'; return; }
    const fd = new FormData(e.target);
    [...files].forEach((f) => fd.append("files", f));
    busy(e.submitter || e.target.querySelector("button"), async () => {
      try {
        const r = await API.form("/api/import/chat", fd);
        $("#chat-result").innerHTML = `<div class="notice ok">${r.results.map((x) => x.error ? `${esc(x.file)}: ${esc(x.error)}` :
          `${esc(x.group)}: ${x.new} new messages${x.duplicates ? `, ${x.duplicates} already imported` : ""}`).join("<br>")}
          <br>Found ${r.stats.events} events, ${r.stats.changes} changes and ${r.stats.tasks} tasks. <a href="#today">Open Today</a></div>`;
        refreshMe();
      } catch (err) { $("#chat-result").innerHTML = `<div class="notice error">${esc(err.message)}</div>`; }
    });
  };
  $("#pdf-form").onsubmit = (e) => {
    e.preventDefault();
    busy(e.target.querySelector("button"), async () => {
      try {
        const r = await API.form("/api/import/pdf", new FormData(e.target));
        $("#pdf-result").innerHTML = `<div class="notice ok">Imported ${esc(r.filename)}: ${r.chunks} searchable sections.</div>${md(r.summary)}`;
      } catch (err) { $("#pdf-result").innerHTML = `<div class="notice error">${esc(err.message)}</div>`; }
    });
  };
  $("#demo").onclick = (e) => busy(e.target, async () => { await API.post("/api/import/demo"); await refreshMe(); toast("Demo data loaded"); location.hash = "#today"; });
  $("#reproc").onclick = (e) => busy(e.target, async () => { await API.post("/api/reprocess"); toast("Everything re-analysed"); });
  $("#wipe").onclick = async () => {
    if (!confirm("Delete all imported groups, messages, documents and tasks from your account? This can't be undone.")) return;
    await API.del("/api/data"); await refreshMe(); toast("All imported data deleted");
  };
};

// -------------------------------------------------------------- profile
pages.profile = async () => {
  const d = await API.get("/api/profile");
  const p = d.profile, wa = d.whatsapp, u = d.user;
  const initials = (p.name || u.name || "?").split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
  const pinned = p.demo_now ? p.demo_now.slice(0, 16) : "";
  main.innerHTML = `<div class="profile-head">
      <div class="avatar">${wa.has_avatar ? '<img src="/api/whatsapp/avatar" alt="Your WhatsApp photo">' : esc(initials)}</div>
      <div><h1>${esc(p.name || u.name)}</h1><div class="muted">${esc(u.email)}</div>
        <div class="small muted">Member since ${esc(fmtTs(u.created_at))}</div></div></div>
    <div class="stats">
      <div class="stat"><b>${d.stats.groups}</b><span>groups</span></div><div class="stat"><b>${d.stats.messages}</b><span>messages read</span></div>
      <div class="stat"><b>${d.stats.tasks_done}/${d.stats.tasks_done + d.stats.tasks_open}</b><span>tasks done</span></div>
      <div class="stat"><b>${d.stats.changes}</b><span>changes caught</span></div></div>
    <div class="two-col">
      <section class="panel"><h2>WhatsApp</h2>
        ${wa.account ? `<dl class="kv"><dt>Status</dt><dd><span class="wa-dot ${wa.alive && wa.state === "ready" ? "on" : ""}"></span>${wa.alive && wa.state === "ready" ? "Connected" : "Not connected right now"}</dd>
          <dt>Name</dt><dd>${esc(wa.account.name || "")}</dd><dt>Number</dt><dd>ending ${esc((wa.account.number || "").slice(-4))}</dd>
          ${wa.account.about ? `<dt>About</dt><dd>${esc(wa.account.about)}</dd>` : ""}<dt>Groups read</dt><dd>${wa.groups_synced}</dd></dl>`
          : '<p class="muted">No number linked yet.</p>'}
        <a class="btn ghost small" href="#whatsapp" style="margin-top:.8rem">${wa.account ? "Manage connection" : "Link WhatsApp"}</a></section>
      <form class="panel" id="pform"><h2>Academic profile</h2>
        <p class="small muted">Used to tell which announcements are for you, like "only for 2nd year".</p>
        <label class="field"><span>Name</span><input type="text" name="name" value="${esc(p.name || "")}"></label>
        <label class="field"><span>Branch</span><input type="text" name="branch" value="${esc(p.branch || "")}" placeholder="CSE - Data Science"></label>
        <div class="row"><label class="field" style="flex:1"><span>Year of study</span><input type="number" name="year" min="1" max="6" value="${p.year || 1}"></label>
          <label class="field" style="flex:1"><span>Graduating batch</span><input type="number" name="grad_year" min="2020" max="2040" value="${p.grad_year || ""}"></label></div>
        <label class="field"><span>Interests</span><input type="text" name="interests" value="${esc((p.interests || []).join(", "))}" placeholder="placements, hackathons, AI"></label>
        <label class="field"><span>Skills</span><input type="text" name="skills" value="${esc((p.skills || []).join(", "))}"></label>
        <label class="field"><span>Teams and clubs</span><input type="text" name="teams" value="${esc((p.teams || []).join(", "))}" placeholder="Team Aagaz"></label>
        <label class="row small" style="margin-bottom:.4rem"><input type="checkbox" id="pin" ${pinned ? "checked" : ""}> Pin "today" to a fixed date (for demos)</label>
        <input type="datetime-local" name="demo_now" value="${esc(pinned)}" class="${pinned ? "" : "hidden"}" aria-label="Pinned date">
        <button class="btn" type="submit" style="margin-top:.9rem" data-busy="Saving">Save profile</button></form>
      <form class="panel" id="pwform"><h2>Password</h2>
        <label class="field"><span>Current password</span><input type="password" name="current" autocomplete="current-password"></label>
        <label class="field"><span>New password</span><input type="password" name="new" autocomplete="new-password"></label>
        <p class="hint">At least 8 characters, with a letter and a number.</p>
        <button class="btn ghost" type="submit">Change password</button><div id="pwmsg"></div></form>
      <section class="panel"><h2>Delete account</h2>
        <p class="small muted">Removes your account, every imported message and your WhatsApp link from this computer.</p>
        <button class="btn danger" id="delacct">Delete my account</button></section></div>`;
  $("#pin").onchange = (e) => $("[name=demo_now]").classList.toggle("hidden", !e.target.checked);
  $("#pform").onsubmit = (e) => {
    e.preventDefault();
    const f = new FormData(e.target), data = Object.fromEntries(f.entries());
    data.demo_now = $("#pin").checked && data.demo_now ? data.demo_now + ":00" : null;
    busy(e.target.querySelector("button[type=submit]"), async () => {
      try { await API.put("/api/profile", data); await refreshMe(); toast("Profile saved and feed re-ranked"); pages.profile(); }
      catch (err) { toast(err.message); }
    });
  };
  $("#pwform").onsubmit = async (e) => {
    e.preventDefault();
    try { await API.post("/api/auth/password", Object.fromEntries(new FormData(e.target).entries())); e.target.reset();
      $("#pwmsg").innerHTML = '<div class="notice ok">Password changed.</div>'; }
    catch (err) { $("#pwmsg").innerHTML = `<div class="notice error">${esc(err.message)}</div>`; }
  };
  $("#delacct").onclick = async () => {
    const pw = prompt("Type your password to permanently delete your account:");
    if (!pw) return;
    try { await API.del("/api/auth/account", { password: pw }); location.href = "/"; } catch (err) { toast(err.message); }
  };
};

// ---------------------------------------------------------------- shell
const TITLES = { today: "Today", changes: "What changed", rumors: "Rumor Shield", deadlines: "Deadlines", tasks: "My tasks",
  ask: "Ask Campus AI", groups: "Groups", resources: "Resources", whatsapp: "WhatsApp", import: "Import chats", profile: "Profile" };
function updateWaDot(on) {
  $("#wa-dot").classList.toggle("on", !!on);
  $("#wa-text").textContent = on ? "WhatsApp live" : "WhatsApp off";
}
function setTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("cp-theme", t); } catch (e) { /* private mode */ }
  const btn = $("#theme-btn");
  btn.innerHTML = `<svg class="i"><use href="#i-${t === "dark" ? "sun" : "moon"}"/></svg>`;
  btn.setAttribute("aria-label", t === "dark" ? "Switch to light mode" : "Switch to dark mode");
}
setTheme(document.documentElement.getAttribute("data-theme") || "light");
$("#theme-btn").onclick = () => setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");

async function refreshMe() {
  state.me = await API.get("/api/auth/me");
  $("#me-name").textContent = state.me.user.name;
  $("#me-email").textContent = state.me.user.email;
  const av = $("#me-avatar");
  av.innerHTML = state.me.whatsapp.has_avatar ? '<img src="/api/whatsapp/avatar" alt="">'
    : esc(state.me.user.name.split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase());
  updateWaDot(state.me.whatsapp.alive && state.me.whatsapp.state === "ready");
  try {
    const t = await API.get("/api/tasks");
    const open = t.filter((x) => x.status === "pending").length;
    $("#count-tasks").textContent = open; $("#count-tasks").classList.toggle("hidden", !open);
  } catch (e) { /* ignore */ }
}

async function route() {
  clearInterval(state.waTimer);
  const page = (location.hash || "#today").slice(1);
  const fn = pages[page] || pages.today;
  $("#crumb").textContent = TITLES[page] || "Today";
  document.title = `${TITLES[page] || "Today"} · CampusPulse AI`;
  document.querySelectorAll(".nav a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === "#" + page ? "page" : "false"));
  document.getElementById("nav").classList.remove("open");
  main.innerHTML = '<p class="muted"><span class="spinner"></span> Loading…</p>';
  try { await fn(); } catch (e) { main.innerHTML = ""; fail(e); }
  main.focus({ preventScroll: true });
}

// Background: while WhatsApp is live, fetch new messages every 20 s and refresh the feed.
async function backgroundSync() {
  if (!state.me || location.hash === "#whatsapp") return;
  if (!(state.me.whatsapp.alive && state.me.whatsapp.state === "ready")) { refreshMe().catch(() => {}); return; }
  try {
    const r = await API.post("/api/whatsapp/sync");
    if (r.new || r.documents) {
      toast(`${r.new} new WhatsApp message${r.new === 1 ? "" : "s"} added`);
      await refreshMe();
      if (["", "#today", "#tasks", "#changes", "#rumors", "#deadlines"].includes(location.hash)) route();
    }
  } catch (e) { /* offline: try again later */ }
}

document.getElementById("logout-btn").onclick = async () => { await API.post("/api/auth/logout"); location.href = "/"; };
document.getElementById("menu-btn").onclick = () => {
  const nav = document.getElementById("nav"); nav.classList.toggle("open");
  document.getElementById("menu-btn").setAttribute("aria-expanded", String(nav.classList.contains("open")));
};
window.addEventListener("hashchange", route);
refreshMe().then(route).catch(() => (location.href = "/"));
state.bgTimer = setInterval(backgroundSync, 20000);
