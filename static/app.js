function midTrunc(name, max = 40) {
  if (name.length <= max) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  const base = dot > 0 ? name.slice(0, dot) : name;
  const keep = max - ext.length - 3;
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return base.slice(0, head) + "…" + base.slice(-tail) + ext;
}

function extractDriveId(url) {
  const m = url.match(/\/file\/d\/([a-zA-Z0-9_-]+)/);
  return m ? m[1] : url;
}

function isValidDriveUrl(val) {
  if (!val) return false;
  if (/drive\.google\.com\/(u\/\d+\/)?file\/d\/[a-zA-Z0-9_-]+/.test(val)) return true;
  if (/^[a-zA-Z0-9_-]{25,60}$/.test(val)) return true;
  return false;
}

function getValidUrls(text) {
  return text.split("\n").map((l) => l.trim()).filter((l) => isValidDriveUrl(l));
}

function isMultiMode() {
  return urlEl.value.split("\n").map((l) => l.trim()).filter(Boolean).length > 1;
}

// ── State ──

let MAX_SLOTS = 1;
let titleReady = false;
let threads = 8;
let titleTimer = null;
let GODMODE = false;
let _clearTimer = null;

const activeDownloads = new Set();
const completedDownloads = new Set();
const expiryTimers = new Map();

// ── DOM refs ──

const urlEl     = document.getElementById("url");
const dlBtn     = document.getElementById("dl-btn");
const btnText   = document.getElementById("btn-text");
const urlFetch  = document.getElementById("url-fetch");
const urlError  = document.getElementById("url-error");
const urlWarn   = document.getElementById("url-warn");
const bottomRow = document.getElementById("bottom-row");
const tVal      = document.getElementById("t-val");
const clearBtn  = document.querySelector(".history-clear-btn");

// ── Tabs ──

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("active", b.id === `tab-${name}`)
  );
  document.querySelectorAll(".tab-pane").forEach((p) =>
    p.classList.toggle("active", p.id === `pane-${name}`)
  );
}

// ── Badge & empty states ──

function updateDownloadsBadge() {
  const badge = document.getElementById("downloads-badge");
  if (!badge) return;
  const count = activeDownloads.size;
  badge.textContent = count;
  badge.style.display = count > 0 ? "" : "none";
}

function updateDownloadsEmpty() {
  const list  = document.getElementById("downloads-list");
  const empty = document.getElementById("downloads-empty");
  if (empty) empty.style.display = list.children.length === 0 ? "" : "none";
}

function updateHistoryEmpty() {
  const list  = document.getElementById("history-list");
  const empty = document.getElementById("history-empty");
  if (empty) empty.style.display = list.children.length === 0 ? "" : "none";
}

// ── Godmode ──

function enableGodmode() {
  bottomRow.style.display = "";
  document.getElementById("t-minus").addEventListener("click", () => {
    if (threads > 1)  { threads--; tVal.textContent = threads; }
  });
  document.getElementById("t-plus").addEventListener("click", () => {
    if (threads < 16) { threads++; tVal.textContent = threads; }
  });
}

if (GODMODE) enableGodmode();

// ── Button sync ──

function syncBtn() {
  const urls  = getValidUrls(urlEl.value);
  const multi = isMultiMode();
  const valid = multi ? urls.length > 0 : urls.length > 0 && titleReady;
  dlBtn.classList.toggle("valid", valid);
  dlBtn.disabled = !valid;
  btnText.textContent = multi && urls.length > 1 ? `Download ${urls.length}` : "Download";
}

function resizeTa() {
  urlEl.style.height = "auto";
  urlEl.style.height = urlEl.scrollHeight + "px";
}

function updateMode() {}

function setUrlError(msg) {
  urlError.textContent = msg;
  urlError.classList.toggle("on", !!msg);
  urlEl.classList.toggle("invalid", !!msg);
}

function setUrlWarn(msg) {
  urlWarn.textContent = msg;
  urlWarn.classList.toggle("on", !!msg);
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function fmtB(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b >= 1e3) return (b / 1e3).toFixed(0) + " KB";
  return b + " B";
}

function fmtSpd(bps) {
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " MB/s";
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + " KB/s";
  return bps + " B/s";
}

function fmtEta(s) {
  if (!isFinite(s) || s <= 0) return "";
  if (s < 60)   return Math.ceil(s) + "s left";
  if (s < 3600) return Math.ceil(s / 60) + "m left";
  return (s / 3600).toFixed(1) + "h left";
}

// ── URL input ──

urlEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && MAX_SLOTS === 1) e.preventDefault();
});

urlEl.addEventListener("input", (e) => {
  if (MAX_SLOTS === 1) {
    const cleaned = e.target.value.replace(/\n/g, "");
    if (cleaned !== e.target.value) e.target.value = cleaned;
  }
  clearTimeout(titleTimer);
  resizeTa();
  updateMode();
  setUrlError("");
  urlEl.classList.remove("validated");

  const v = e.target.value.trim();

  if (!v) {
    titleReady = false;
    syncBtn();
    return;
  }

  if (isMultiMode()) {
    titleReady = true;
    syncBtn();
    return;
  }

  titleReady = false;
  syncBtn();
  titleTimer = setTimeout(() => fetchTitle(v), 620);
});

async function fetchTitle(url) {
  urlFetch.classList.add("on");
  btnText.textContent = "Checking…";
  setUrlError("");
  try {
    const r = await fetch("/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await r.json();
    if (!r.ok || !data.title) {
      setUrlError(
        "Could not fetch video info. Make sure the file is a video and is publicly accessible.",
      );
      return;
    }
    titleReady = true;
    urlEl.classList.add("validated");
    syncBtn();
  } catch {
    setUrlError("Network error — is the server running?");
  } finally {
    urlFetch.classList.remove("on");
    syncBtn();
  }
}

// ── Job control ──

async function controlJob(action, jobId) {
  await fetch(`/${action}/${jobId}`, { method: "POST" });
}

function setCardActions(jobId, state, refs) {
  const act = refs.act;
  if (state === "queued" || state === "fetching") {
    act.innerHTML = `<button class="ctrl-btn stop-btn" onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === "downloading") {
    act.innerHTML = `
      <button class="ctrl-btn pause-btn" onclick="controlJob('pause','${jobId}')">Pause</button>
      <button class="ctrl-btn stop-btn"  onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === "paused") {
    act.innerHTML = `
      <button class="ctrl-btn resume-btn" onclick="controlJob('resume','${jobId}')">Resume</button>
      <button class="ctrl-btn stop-btn"   onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === "done") {
    act.innerHTML = `
      <a class="save-btn" href="/download/${jobId}">Save file</a>
      <button class="dismiss-btn" onclick="dismissCard('${jobId}')">Dismiss</button>`;
  } else if (state === "error") {
    act.innerHTML = `
      <button class="ctrl-btn retry-btn" onclick="retryJob('${jobId}')">Retry</button>
      <button class="dismiss-btn" onclick="dismissCard('${jobId}')">Dismiss</button>`;
  } else {
    act.innerHTML = `<button class="dismiss-btn" onclick="dismissCard('${jobId}')">Dismiss</button>`;
  }
}

function createCard(jobId) {
  const list = document.getElementById("downloads-list");
  const card = document.createElement("div");
  card.className = "dl-card";
  card.id = `card-${jobId}`;
  card.innerHTML = `
    <div class="card-head">
      <div class="card-name" id="cname-${jobId}">—</div>
      <div class="card-tag"  id="ctag-${jobId}">Starting</div>
    </div>
    <div class="card-pbar">
      <div class="card-pbar-fill indeterminate" id="cpbar-${jobId}"></div>
    </div>
    <div class="card-stats">
      <span id="cspd-${jobId}"></span>
      <span id="csz-${jobId}"></span>
    </div>
    <div class="card-actions" id="cact-${jobId}">
      <button class="ctrl-btn stop-btn" onclick="controlJob('stop','${jobId}')">Stop</button>
    </div>
  `;
  list.insertBefore(card, list.firstChild);
  updateDownloadsEmpty();
  return card;
}

function trackJob(jobId, card, driveId) {
  const refs = {
    tag:  document.getElementById(`ctag-${jobId}`),
    name: document.getElementById(`cname-${jobId}`),
    pbar: document.getElementById(`cpbar-${jobId}`),
    spd:  document.getElementById(`cspd-${jobId}`),
    sz:   document.getElementById(`csz-${jobId}`),
    act:  document.getElementById(`cact-${jobId}`),
  };

  const t0 = Date.now();
  let lb = 0, lt = t0, total = 0, finished = false;
  let es;

  function finish(succeeded = false) {
    finished = true;
    activeDownloads.delete(driveId);
    if (succeeded) completedDownloads.add(driveId);
    updateDownloadsBadge();
  }

  function markError(message) {
    finish();
    refs.tag.textContent = "Error";
    refs.tag.classList.add("red");
    refs.pbar.className = "card-pbar-fill";
    refs.pbar.style.width = "0%";
    card.classList.add("error");
    card.insertAdjacentHTML("beforeend", `<div class="card-err-msg">${esc(message)}</div>`);
    setCardActions(jobId, "error", refs);
  }

  const handlers = {
    queued() {
      refs.tag.textContent = "Starting";
      setCardActions(jobId, "queued", refs);
    },
    status(msg) {
      if (msg.message.startsWith("Downloading:")) {
        refs.tag.textContent = "Downloading";
        const fname = msg.message.replace("Downloading: ", "");
        refs.name.textContent = midTrunc(fname);
        refs.name.title = fname;
        card.classList.add("downloading");
        card.classList.remove("paused");
        setCardActions(jobId, "downloading", refs);
      } else {
        card.classList.remove("downloading");
        setCardActions(jobId, "fetching", refs);
      }
    },
    progress(msg) {
      total = msg.total;
      const now = Date.now(), dt = (now - lt) / 1000, db = msg.downloaded - lb;
      if (dt > 0.3) {
        const bps = db / dt;
        const eta = bps > 0 && msg.total > 0 ? (msg.total - msg.downloaded) / bps : Infinity;
        refs.spd.textContent = fmtSpd(bps) + (eta < Infinity ? "  ·  " + fmtEta(eta) : "");
        lb = msg.downloaded;
        lt = now;
      }
      if (msg.total > 0) {
        const pct = Math.min(100, (msg.downloaded / msg.total) * 100);
        refs.pbar.className = "card-pbar-fill";
        refs.pbar.style.width = pct.toFixed(1) + "%";
        refs.sz.textContent = fmtB(msg.downloaded) + " / " + fmtB(msg.total);
      } else {
        refs.sz.textContent = fmtB(msg.downloaded);
      }
    },
    paused() {
      refs.tag.textContent = "Paused";
      refs.spd.textContent = "";
      card.classList.remove("downloading");
      card.classList.add("paused");
      setCardActions(jobId, "paused", refs);
    },
    resumed() {
      refs.tag.textContent = "Downloading";
      card.classList.add("downloading");
      card.classList.remove("paused");
      setCardActions(jobId, "downloading", refs);
    },
    done(msg) {
      es.close();
      finish(true);
      refs.pbar.className = "card-pbar-fill";
      refs.pbar.style.width = "100%";
      refs.tag.textContent = "Done";
      refs.tag.classList.add("green");
      refs.name.textContent = midTrunc(msg.filename);
      refs.name.title = msg.filename;
      refs.spd.textContent = "";
      refs.sz.textContent = [
        total ? fmtB(total) : "",
        ((Date.now() - t0) / 1000).toFixed(1) + "s",
      ].filter(Boolean).join(" · ");
      card.classList.add("done");
      card.classList.remove("paused");
      setCardActions(jobId, "done", refs);
      loadHistory();
      switchTab("downloads");

      if (msg.ttl) startExpiry(jobId, card, msg.ttl);
    },
    error(msg) {
      es.close();
      markError(msg.message);
    },
    stopped() {
      es.close();
      finish();
      refs.tag.textContent = "Stopped";
      refs.spd.textContent = "";
      refs.sz.textContent = "";
      refs.pbar.className = "card-pbar-fill";
      refs.pbar.style.width = "0%";
      card.classList.add("stopped");
      card.classList.remove("downloading", "paused");
      setCardActions(jobId, "stopped", refs);
    },
  };

  let reconnects = 0;

  es = new EventSource(`/progress/${jobId}`);

  es.onopen = () => { reconnects = 0; };

  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "ping") return;
    handlers[msg.type]?.(msg);
  };

  es.onerror = () => {
    if (finished) return;
    reconnects++;
    if (reconnects < 4) return;
    es.close();
    markError("Connection lost.");
  };
}

// ── History ──

function fmtDate(iso) {
  const d = new Date(iso);
  return (
    d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
    " · " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  );
}

function renderHistoryEntry(entry) {
  const el = document.createElement("div");
  el.className = "history-entry";
  el.id = `hentry-${entry.id}`;
  el.innerHTML = `
    <div class="history-name" title="${esc(entry.filename)}">${esc(midTrunc(entry.filename))}</div>
    <div class="history-meta">${entry.size ? fmtB(entry.size) + " · " : ""}${fmtDate(entry.downloaded_at)}</div>
    <button class="history-del" onclick="deleteHistoryEntry('${entry.id}')">×</button>
  `;
  return el;
}

async function loadHistory() {
  const entries = await fetch("/history").then((r) => r.json()).catch(() => []);
  const list = document.getElementById("history-list");
  list.innerHTML = "";
  entries.forEach((e) => list.appendChild(renderHistoryEntry(e)));
  updateHistoryEmpty();
}

async function deleteHistoryEntry(id) {
  await fetch(`/history/${id}`, { method: "DELETE" });
  document.getElementById(`hentry-${id}`)?.remove();
  updateHistoryEmpty();
}

async function clearHistory() {
  if (_clearTimer) {
    clearTimeout(_clearTimer);
    _clearTimer = null;
    clearBtn.textContent = "Clear all";
    clearBtn.classList.remove("confirm");
    await fetch("/history", { method: "DELETE" });
    document.getElementById("history-list").innerHTML = "";
    updateHistoryEmpty();
  } else {
    clearBtn.textContent = "Sure?";
    clearBtn.classList.add("confirm");
    _clearTimer = setTimeout(() => {
      _clearTimer = null;
      clearBtn.textContent = "Clear all";
      clearBtn.classList.remove("confirm");
    }, 3000);
  }
}

// ── Retry ──

async function retryJob(jobId) {
  const card = document.getElementById(`card-${jobId}`);
  const url = card?.dataset.url;
  if (!url) return;

  dismissCard(jobId);

  const result = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, output: "", threads, chunk_size: 65536 }),
  })
    .then((r) => r.json().then((d) => ({ ok: r.ok, data: d, url })))
    .catch(() => null);

  if (!result?.ok) {
    if (result?.data?.error) setUrlError(result.data.error);
    return;
  }

  const driveId = extractDriveId(url);
  activeDownloads.add(driveId);
  completedDownloads.delete(driveId);
  const newCard = createCard(result.data.job_id);
  newCard.dataset.driveId = driveId;
  newCard.dataset.url = url;
  trackJob(result.data.job_id, newCard, driveId);
  updateDownloadsBadge();
}

// ── Expiry countdown ──

function fmtExpiry(secs) {
  if (secs <= 0)   return null;
  if (secs < 60)   return "expires soon";
  const mins = Math.round(secs / 60);
  if (mins < 60)   return `expires in ${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return `expires in ${h}h${m > 0 ? ` ${m}m` : ""}`;
}

function startExpiry(jobId, card, ttl) {
  const el = document.getElementById(`cspd-${jobId}`);
  if (!el) return;
  el.classList.add("card-expiry");

  let remaining = ttl;

  function tick() {
    const label = fmtExpiry(remaining);
    if (!label) {
      dismissCard(jobId);
      return;
    }
    el.textContent = label;
    el.classList.toggle("soon", remaining < 300);
    remaining -= 30;
  }

  tick();
  const id = setInterval(tick, 30_000);
  expiryTimers.set(jobId, id);
}

// ── Card dismiss ──

function dismissCard(jobId) {
  clearInterval(expiryTimers.get(jobId));
  expiryTimers.delete(jobId);
  const card = document.getElementById(`card-${jobId}`);
  completedDownloads.delete(card?.dataset.driveId);
  fetch(`/delete/${jobId}`, { method: "DELETE" });
  card?.remove();
  updateDownloadsEmpty();
}

// ── Form reset ──

function resetForm() {
  urlEl.value = "";
  urlEl.style.height = "";
  urlEl.classList.remove("validated");
  titleReady = false;
  setUrlError("");
  setUrlWarn("");
  syncBtn();
  urlEl.focus();
}

// ── Form submit ──

document.getElementById("dl-form").addEventListener("submit", async (e) => {
  e.preventDefault();

  const allUrls = getValidUrls(urlEl.value);
  if (!allUrls.length) return;

  const isDupe  = (u) => activeDownloads.has(extractDriveId(u)) || completedDownloads.has(extractDriveId(u));
  const dupes   = allUrls.filter((u) => isDupe(u));
  const urls    = allUrls.filter((u) => !isDupe(u));

  if (dupes.length) {
    const downloading = dupes.filter((u) => activeDownloads.has(extractDriveId(u))).length;
    const downloaded  = dupes.filter((u) => completedDownloads.has(extractDriveId(u))).length;
    const parts = [];
    if (downloading) parts.push(`${downloading} already downloading`);
    if (downloaded)  parts.push(`${downloaded} already downloaded`);
    setUrlWarn(`Skipped — ${parts.join(", ")}`);
  } else {
    setUrlWarn("");
  }

  if (!urls.length) { syncBtn(); return; }

  dlBtn.disabled = true;
  dlBtn.classList.add("loading");
  btnText.textContent = "Starting…";

  const results = [];
  for (const url of urls) {
    const result = await fetch("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, output: "", threads, chunk_size: 65536 }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, status: r.status, data: d, url })))
      .catch(() => null);
    results.push(result);
  }

  dlBtn.classList.remove("loading");
  btnText.textContent = "Download";

  let anyStarted = false;
  for (const result of results) {
    if (!result) continue;
    if (!result.ok) {
      if (result.data?.error) setUrlError(result.data.error);
      continue;
    }
    const driveId = extractDriveId(result.url);
    activeDownloads.add(driveId);
    const card = createCard(result.data.job_id);
    card.dataset.driveId = driveId;
    card.dataset.url = result.url;
    trackJob(result.data.job_id, card, driveId);
    anyStarted = true;
  }

  updateDownloadsBadge();

  if (!anyStarted) {
    setUrlError("Failed to start downloads. Is the server running?");
    syncBtn();
    return;
  }

  switchTab("downloads");
  resetForm();
});

// ── Key modal ──

const keyBtn      = document.getElementById("key-btn");
const keyBackdrop = document.getElementById("modal-backdrop");
const keyInp      = document.getElementById("key-inp");
const keyStatus   = document.getElementById("key-status");

function openKeyModal() {
  if (keyBtn.disabled) return;
  keyBackdrop.classList.add("open");
  keyBtn.classList.add("active");
  keyStatus.textContent = "";
  keyInp.value = "";
  setTimeout(() => keyInp.focus(), 50);
}

function closeKeyModal() {
  keyBackdrop.classList.remove("open");
  keyBtn.classList.remove("active");
}

keyBtn.addEventListener("click", openKeyModal);
document.getElementById("modal-cancel").addEventListener("click", closeKeyModal);
keyBackdrop.addEventListener("click", (e) => { if (e.target === keyBackdrop) closeKeyModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeKeyModal(); });

document.getElementById("key-submit").addEventListener("click", submitKey);
keyInp.addEventListener("keydown", (e) => { if (e.key === "Enter") submitKey(); });

async function submitKey() {
  const code = keyInp.value.trim();
  if (!code) return;
  keyStatus.textContent = "…";
  try {
    const r    = await fetch("/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await r.json();
    if (data.slots > 1) {
      MAX_SLOTS = data.slots;
      urlEl.placeholder = "Paste links, one per line";
      document.getElementById("key-btn-label").textContent = "Activated";
      keyBtn.classList.remove("active");
      keyBtn.classList.add("unlocked");
      keyBtn.disabled = true;
      if (data.slots >= 999) enableGodmode();
      closeKeyModal();
    } else {
      keyStatus.style.color = "var(--red)";
      keyStatus.textContent = "Invalid key";
    }
  } catch {
    keyStatus.style.color = "var(--red)";
    keyStatus.textContent = "Network error";
  }
}

// ── Init ──

fetch("/config")
  .then((r) => r.json())
  .then((data) => {
    MAX_SLOTS = data.slots || 1;
    GODMODE   = MAX_SLOTS >= 999;
    if (MAX_SLOTS > 1) {
      urlEl.placeholder = "Paste links, one per line";
      document.getElementById("key-btn-label").textContent = "Activated";
      keyBtn.classList.add("unlocked");
      keyBtn.disabled = true;
    }
    if (GODMODE) enableGodmode();
  })
  .catch(() => {});

syncBtn();
updateDownloadsEmpty();
loadHistory();
