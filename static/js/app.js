// ── URL input ──

urlEl.addEventListener("input", (e) => {
  clearTimeout(titleTimer);
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

  const url = getValidUrl(urlEl.value);
  if (!url) return;

  const driveId = extractDriveId(url);
  if (activeDownloads.has(driveId)) { setUrlWarn("Already downloading"); return; }
  if (completedDownloads.has(driveId)) { setUrlWarn("Already downloaded"); return; }
  setUrlWarn("");

  dlBtn.disabled = true;
  dlBtn.classList.add("loading");
  btnText.textContent = "Starting…";

  const password = currentSource === "zoom"
    ? (document.getElementById("password-inp")?.value || "")
    : "";

  const result = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, output: "", threads: 16, chunk_size: 65536, source: currentSource, password }),
  })
    .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
    .catch(() => null);

  dlBtn.classList.remove("loading");
  btnText.textContent = "Download";

  if (!result?.ok) {
    setUrlError(result?.data?.error || "Failed to start download. Is the server running?");
    syncBtn();
    return;
  }

  activeDownloads.add(driveId);
  const card = createCard(result.data.job_id);
  card.dataset.driveId  = driveId;
  card.dataset.url      = url;
  card.dataset.source   = currentSource;
  card.dataset.password = password;
  trackJob(result.data.job_id, card, driveId);

  updateDownloadsBadge();
  switchTab("downloads");
  resetForm();
});

// ── Init ──

syncBtn();
updateDownloadsEmpty();
loadHistory();
