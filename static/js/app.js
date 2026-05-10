// ── URL input ──

urlEl.addEventListener("input", (e) => {
  clearTimeout(titleTimer);
  resizeTa();
  setUrlError("");
  urlEl.classList.remove("validated");

  const v = e.target.value.trim();
  if (!v) { titleReady = false; syncBtn(); return; }

  if (currentSource === "zoom") {
    titleReady = isValidZoomUrl(v);
    if (titleReady) urlEl.classList.add("validated");
    syncBtn();
    return;
  }

  if (currentSource === "gdocs") {
    titleReady = isValidGdocsUrl(v);
    if (titleReady) urlEl.classList.add("validated");
    syncBtn();
    return;
  }

  if (isMultiMode()) { titleReady = true; syncBtn(); return; }

  titleReady = false;
  syncBtn();
  titleTimer = setTimeout(() => fetchTitle(v), 620);
});

async function fetchTitle(url) {
  urlFetch.classList.add("on");
  btnText.textContent = "Checking…";
  setUrlError("");
  try {
    const r    = await fetch("/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await r.json();
    if (!r.ok || !data.title) {
      setUrlError("Could not fetch video info. Make sure the file is a video and is publicly accessible.");
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

// ── Form submit ──

document.getElementById("dl-form").addEventListener("submit", async (e) => {
  e.preventDefault();

  const allUrls = getValidUrls(urlEl.value);
  if (!allUrls.length) return;

  const isDupe = (u) => activeDownloads.has(extractDriveId(u)) || completedDownloads.has(extractDriveId(u));
  const dupes  = allUrls.filter(isDupe);
  const urls   = allUrls.filter((u) => !isDupe(u));

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

  const password = currentSource === "zoom"
    ? (document.getElementById("password-inp")?.value || "")
    : "";

  const results = [];
  for (const url of urls) {
    const result = await fetch("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, output: "", threads: 16, chunk_size: 65536, source: currentSource, password }),
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
    card.dataset.url     = result.url;
    card.dataset.source  = currentSource;
    card.dataset.password = password;
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

// ── Init ──

syncBtn();
updateDownloadsEmpty();
loadHistory();
