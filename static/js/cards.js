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
      <button class="copy-btn" id="copy-${jobId}" onclick="copyLink('${jobId}')">Copy link</button>
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

function trackJob(jobId, card, urlKey) {
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
    activeDownloads.delete(urlKey);
    if (succeeded) completedDownloads.add(urlKey);
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
      } else if (msg.message.startsWith("Downloading document") ||
                 msg.message.startsWith("Downloading form")    ||
                 msg.message.startsWith("Parsing")             ||
                 msg.message.startsWith("Fetching images")     ||
                 msg.message.startsWith("Processing")          ||
                 msg.message.startsWith("Building DOCX")) {
        refs.tag.textContent  = "Converting";
        refs.name.textContent = msg.message;
        card.classList.remove("downloading");
        setCardActions(jobId, "fetching", refs);
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
      const sizeText = total ? fmtB(total) : "";
      refs.sz.textContent = sizeText;
      card.classList.add("done");
      card.classList.remove("paused");
      setCardActions(jobId, "done", refs);
      if (msg.history_entry) prependHistoryEntry(msg.history_entry);
      else                   loadHistory();
      switchTab("downloads");
      if (msg.ttl) startExpiry(jobId, card, msg.ttl, sizeText);
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
    console.error(`[sse] job ${jobId} error (reconnect ${reconnects})`);
    if (reconnects < 4) return;
    es.close();
    markError("Connection lost.");
  };
}

async function copyLink(jobId) {
  const url = `${location.origin}/download/${jobId}`;
  const btn = document.getElementById(`copy-${jobId}`);
  try {
    await navigator.clipboard.writeText(url);
    if (btn) {
      btn.textContent = "Copied!";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = "Copy link";
        btn.classList.remove("copied");
      }, 2000);
    }
  } catch {
    if (btn) btn.textContent = "Failed";
  }
}

async function retryJob(jobId) {
  const card = document.getElementById(`card-${jobId}`);
  const url  = card?.dataset.url;
  if (!url) return;

  dismissCard(jobId);

  const src = card?.dataset.source || "gdrive";
  const pw  = card?.dataset.password || "";
  const result = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, output: "", threads: 16, chunk_size: 65536, source: src, password: pw }),
  })
    .then((r) => r.json().then((d) => ({ ok: r.ok, data: d, url })))
    .catch(() => null);

  if (!result?.ok) {
    if (result?.data?.error) setUrlError(result.data.error);
    return;
  }

  const urlKey = src === "gdrive" ? extractDriveId(url) : url;
  activeDownloads.add(urlKey);
  completedDownloads.delete(urlKey);
  const newCard = createCard(result.data.job_id);
  newCard.dataset.urlKey = urlKey;
  newCard.dataset.url = url;
  newCard.dataset.source = src;
  trackJob(result.data.job_id, newCard, urlKey);
  updateDownloadsBadge();
}

function fmtExpiry(secs) {
  if (secs <= 0)   return null;
  if (secs < 60)   return "expires soon";
  const mins = Math.round(secs / 60);
  if (mins < 60)   return `expires in ${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return `expires in ${h}h${m > 0 ? ` ${m}m` : ""}`;
}

function startExpiry(jobId, card, ttl, sizeText = "") {
  const el = document.getElementById(`csz-${jobId}`);
  if (!el) return;
  el.classList.add("card-expiry");
  let remaining = ttl;

  function tick() {
    const label = fmtExpiry(remaining);
    if (!label) { dismissCard(jobId); return; }
    el.textContent = [sizeText, label].filter(Boolean).join(" · ");
    el.classList.toggle("soon", remaining < 300);
    remaining -= 30;
  }

  tick();
  expiryTimers.set(jobId, setInterval(tick, 30_000));
}

function dismissCard(jobId) {
  clearInterval(expiryTimers.get(jobId));
  expiryTimers.delete(jobId);
  const card = document.getElementById(`card-${jobId}`);
  completedDownloads.delete(card?.dataset.urlKey);
  fetch(`/delete/${jobId}`, { method: "DELETE" });
  card?.remove();
  updateDownloadsEmpty();
}
