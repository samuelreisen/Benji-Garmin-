"use strict";
/* Benji Coach front end. Model text is always rendered with textContent, never innerHTML. */

const $ = (id) => document.getElementById(id);
const TABS = { today: "Today", coach: "Coach", trends: "Trends", profile: "Profile" };
const SUGGESTIONS = [
  "Should I train hard today?",
  "How's my recovery trending?",
  "What should this week look like?",
  "Am I overdoing it?",
];
const METRIC_INFO = {
  training_readiness: { label: "Readiness", unit: "", higherIsBetter: true },
  sleep_hours: { label: "Sleep", unit: "h", higherIsBetter: true },
  sleep_score: { label: "Sleep score", unit: "", higherIsBetter: true },
  hrv_ms: { label: "HRV", unit: "ms", higherIsBetter: true },
  resting_hr: { label: "Resting HR", unit: "bpm", higherIsBetter: false },
  body_battery_high: { label: "Body battery", unit: "", higherIsBetter: true },
  stress_avg: { label: "Stress", unit: "", higherIsBetter: false },
  steps: { label: "Steps", unit: "", higherIsBetter: true },
};
const TODAY_TILES = ["training_readiness", "sleep_hours", "hrv_ms", "resting_hr", "body_battery_high", "stress_avg"];

let currentTab = "today";
let loaded = { today: false, coach: false, trends: false, profile: false };

/* ---------- helpers ---------- */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.append(c);
  return node;
}

async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json", "X-Requested-With": "benji" },
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (res.status === 401 && path !== "/login") showLogin();
  if (!res.ok) {
    const err = new Error((data && data.detail) || "Something went wrong. Try again.");
    err.status = res.status;
    throw err;
  }
  return data;
}

function inlineBold(parent, line) {
  line.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) parent.append(el("strong", { text: part.slice(2, -2) }));
    else if (part) parent.append(document.createTextNode(part));
  });
}

/* Tiny safe markdown: paragraphs, "- " lists, **bold**. Built from DOM nodes only. */
function renderText(container, text) {
  container.replaceChildren();
  let list = null;
  String(text).split(/\r?\n/).forEach((raw) => {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      if (!list) { list = el("ul"); container.append(list); }
      const li = el("li"); inlineBold(li, bullet[1]); list.append(li);
    } else if (line) {
      list = null;
      const p = el("p"); inlineBold(p, line); container.append(p);
    } else {
      list = null;
    }
  });
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function when(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}

function fmt(n, unit) {
  if (n === null || n === undefined) return "No data";
  const v = Math.abs(n) >= 1000 ? Math.round(n).toLocaleString() : Number(n.toFixed(1));
  return `${v}${unit ? " " + unit : ""}`;
}

/* ---------- auth + navigation ---------- */
function showLogin() {
  $("app-view").hidden = true;
  $("login-view").hidden = false;
  loaded = { today: false, coach: false, trends: false, profile: false };
  $("password").focus();
}

function showApp() {
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  switchTab(currentTab, true);
}

function switchTab(tab, force = false) {
  if (tab === currentTab && !force && loaded[tab]) return;
  currentTab = tab;
  $("screen-title").textContent = TABS[tab];
  document.querySelectorAll(".screen").forEach((s) => { s.hidden = s.id !== "screen-" + tab; });
  document.querySelectorAll(".tab").forEach((t) => {
    if (t.dataset.tab === tab) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
  });
  $("sync-btn").hidden = tab === "profile";
  if (loaded[tab]) return;
  loaded[tab] = true;
  ({ today: loadToday, coach: loadCoach, trends: loadTrends, profile: loadProfile })[tab]();
}

/* ---------- Today ---------- */
async function loadToday() {
  loadBriefing(false);
  try {
    const snap = await api("/snapshot");
    renderTiles(snap);
    renderTraining(snap);
    $("sync-status").textContent = snap.last_sync ? "Last synced " + when(snap.last_sync) : "Not synced yet. Hit Sync now.";
  } catch (e) {
    $("sync-status").textContent = e.message;
  }
}

async function loadBriefing(refresh) {
  const body = $("briefing-body");
  body.replaceChildren(el("p", { class: "muted", text: "Your coach is reading your numbers..." }));
  try {
    const data = refresh ? await api("/briefing/refresh", { method: "POST" }) : await api("/briefing");
    renderText(body, data.text);
  } catch (e) {
    body.replaceChildren(el("p", { class: "muted", text: e.message }));
  }
}

function renderTiles(snap) {
  const grid = $("metric-grid");
  grid.replaceChildren();
  TODAY_TILES.forEach((key) => {
    const info = METRIC_INFO[key];
    const m = snap.metrics[key];
    const value = el("div", { class: "value" });
    if (m.latest === null) {
      value.textContent = "No data";
      value.classList.add("muted");
    } else {
      value.append(document.createTextNode(String(Number(m.latest.toFixed(1)))));
      if (info.unit) value.append(el("span", { class: "unit", text: info.unit }));
    }
    const d = m.latest_vs_28d_avg_pct;
    let deltaText = "Syncing will fill this in";
    let cls = "delta";
    if (d !== null && d !== undefined) {
      const arrow = d > 1 ? "Up" : d < -1 ? "Down" : "Level";
      const better = d > 1 ? info.higherIsBetter : d < -1 ? !info.higherIsBetter : null;
      deltaText = arrow === "Level" ? "In line with your 28-day average" : `${arrow} ${Math.abs(d)}% on your 28-day average`;
      if (better === true) cls += " good"; else if (better === false) cls += " warn";
    } else if (m.latest !== null) {
      deltaText = "Not enough history to compare yet";
    }
    grid.append(el("div", { class: "tile" }, [
      el("div", { class: "label", text: info.label }), value, el("div", { class: cls, text: deltaText }),
    ]));
  });
}

function row(title, sub, end) {
  return el("div", { class: "hig-row" }, [
    el("div", { class: "row-main" }, [el("div", { class: "row-title", text: title }), sub ? el("div", { class: "row-sub", text: sub }) : null]),
    end ? el("div", { class: "row-end", text: end }) : null,
  ]);
}

function renderTraining(snap) {
  const box = $("training");
  box.replaceChildren();
  const t = snap.training;
  const w = t.last_7_days;
  if (!t.last_activity && w.sessions === 0) {
    box.append(el("div", { class: "hig-row empty-row", text: "No activities yet. Sync to pull your workouts in." }));
    return;
  }
  box.append(row("Last 7 days", plural(w.hard_sessions, "hard session"), `${plural(w.sessions, "session")}, ${w.distance_km} km, ${w.duration_min} min`));
  const p = t.weekly_average_of_prior_21_days;
  box.append(row("Usual week", "Weekly average, 3 weeks before", `${p.sessions} sessions, ${p.distance_km} km`));
  if (t.last_activity) {
    const a = t.last_activity;
    const when = a.days_ago === 0 ? "Today" : a.days_ago === 1 ? "Yesterday" : `${a.days_ago} days ago`;
    box.append(row(a.name || a.type, when, `${a.distance_km ?? "-"} km, ${a.duration_min ?? "-"} min`));
  }
}

/* ---------- Coach ---------- */
function addBubble(role, text) {
  const b = el("div", { class: "bubble prose " + role });
  if (role === "model") renderText(b, text); else b.textContent = text;
  $("chat-log").append(b);
  b.scrollIntoView({ block: "end", behavior: "smooth" });
  return b;
}

function updateChatEmpty() {
  const has = $("chat-log").children.length > 0;
  $("chat-empty").hidden = has;
  $("chat-clear").hidden = !has;
}

async function loadCoach() {
  const chips = $("chips");
  SUGGESTIONS.forEach((s) => {
    const b = el("button", { class: "hig-btn", type: "button", text: s });
    b.addEventListener("click", () => sendChat(s));
    chips.append(b);
  });
  try {
    const { messages } = await api("/chat");
    messages.forEach((m) => addBubble(m.role, m.content));
  } catch (_) { /* leave empty state */ }
  updateChatEmpty();
}

async function sendChat(text) {
  const message = text.trim();
  if (!message) return;
  $("chat-input").value = "";
  $("chat-send").disabled = true;
  addBubble("user", message);
  updateChatEmpty();
  const typing = addBubble("model", "");
  typing.classList.add("typing");
  typing.textContent = "Thinking...";
  try {
    const { reply } = await api("/chat", { method: "POST", body: { message } });
    typing.remove();
    addBubble("model", reply);
  } catch (e) {
    typing.remove();
    addBubble("error", e.message);
  } finally {
    $("chat-send").disabled = false;
    $("chat-input").focus();
  }
}

/* ---------- Trends ---------- */
function sparkline(points) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", "0 0 96 32");
  svg.setAttribute("aria-hidden", "true");
  if (points.length < 2) return svg;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * 92 + 2;
    const y = 30 - ((p.value - min) / span) * 28;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = document.createElementNS(NS, "polyline");
  line.setAttribute("points", coords.join(" "));
  svg.append(line);
  return svg;
}

async function loadTrends() {
  const list = $("trend-list");
  list.replaceChildren(el("div", { class: "hig-row empty-row", text: "Loading..." }));
  try {
    const [series, snap] = await Promise.all([api("/trends"), api("/snapshot")]);
    list.replaceChildren();
    Object.keys(METRIC_INFO).forEach((key) => {
      const m = snap.metrics[key];
      const info = METRIC_INFO[key];
      const sub = `7-day ${fmt(m.avg_7d, info.unit)}, 28-day ${fmt(m.avg_28d, info.unit)}`;
      const r = el("div", { class: "hig-row" }, [
        el("div", { class: "row-main" }, [el("div", { class: "row-title", text: info.label }), el("div", { class: "row-sub", text: sub })]),
        sparkline(series[key] || []),
      ]);
      list.append(r);
    });
  } catch (e) {
    list.replaceChildren(el("div", { class: "hig-row empty-row", text: e.message }));
  }
}

/* ---------- Profile ---------- */
const lines = (s) => s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);

async function loadProfile() {
  try {
    const p = await api("/profile");
    $("p-name").value = p.name || "";
    $("p-age").value = p.age ?? "";
    $("p-goals").value = p.goals.join("\n");
    $("p-injuries").value = p.injuries.join("\n");
    $("p-schedule").value = p.weekly_schedule || "";
    $("p-equipment").value = p.equipment.join("\n");
    $("p-swearing").checked = !!p.swearing;
  } catch (e) {
    $("profile-status").textContent = e.message;
  }
}

/* ---------- wiring ---------- */
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("login-error");
  err.hidden = true;
  try {
    await api("/login", { method: "POST", body: { password: $("password").value } });
    $("password").value = "";
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST" }); } catch (_) { /* already out */ }
  showLogin();
});

$("sync-btn").addEventListener("click", async () => {
  const btn = $("sync-btn");
  btn.disabled = true;
  $("sync-status").textContent = "Syncing with Garmin. First time can take a minute...";
  try {
    const r = await api("/sync", { method: "POST" });
    $("sync-status").textContent = `Synced ${r.synced_days} days and ${r.activities} activities.`;
    loaded.today = loaded.trends = false;
    if (currentTab === "today" || currentTab === "trends") { loaded[currentTab] = true; ({ today: loadToday, trends: loadTrends })[currentTab](); }
  } catch (e) {
    $("sync-status").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

$("briefing-refresh").addEventListener("click", () => loadBriefing(true));
$("chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("chat-input").value); });
$("chat-clear").addEventListener("click", async () => {
  try { await api("/chat", { method: "DELETE" }); } catch (_) { return; }
  $("chat-log").replaceChildren();
  updateChatEmpty();
});

$("profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = $("profile-status");
  status.textContent = "Saving...";
  const age = $("p-age").value.trim();
  try {
    await api("/profile", {
      method: "PUT",
      body: {
        name: $("p-name").value.trim() || "Benji",
        age: age ? Number(age) : null,
        goals: lines($("p-goals").value),
        injuries: lines($("p-injuries").value),
        weekly_schedule: $("p-schedule").value.trim(),
        equipment: lines($("p-equipment").value),
        swearing: $("p-swearing").checked,
      },
    });
    status.textContent = "Saved. The coach will use this from the next message.";
  } catch (ex) {
    status.textContent = ex.message;
  }
});

(async function init() {
  try {
    const me = await api("/me");
    if (me.authenticated) showApp(); else showLogin();
  } catch (_) {
    showLogin();
  }
})();
