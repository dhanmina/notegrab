document.getElementById("password-inp").addEventListener("input", () => {
  setUrlError("");
  setUrlWarn("");
});


urlEl.addEventListener("input", (e) => {
  clearTimeout(titleTimer);
  setUrlError("");
  urlEl.classList.remove("validated");

  const v = e.target.value.trim();
  if (!v) {
    detectedVideoSource = null;
    detectedDocsSource  = null;
    titleReady = false;
    document.getElementById("password-row").style.display = "none";
    syncBtn();
    return;
  }

  if (currentSource === "video") {
    const isZoom  = isValidZoomUrl(v);
    const isDrive = isValidDriveUrl(v);
    document.getElementById("password-row").style.display = isZoom ? "" : "none";
    if (isZoom) {
      detectedVideoSource = "zoom";
      titleReady = true;
      urlEl.classList.add("validated");
      syncBtn();
    } else if (isDrive) {
      detectedVideoSource = "gdrive";
      titleReady = false;
      syncBtn();
      titleTimer = setTimeout(() => fetchTitle(v), 620);
    } else {
      detectedVideoSource = null;
      titleReady = false;
      syncBtn();
    }
    return;
  }

  if (currentSource === "docs") {
    const isGdocs  = isValidGdocsUrl(v);
    const isGforms = isValidGformsUrl(v);
    if (isGdocs) {
      detectedDocsSource = "gdocs";
      titleReady = true;
      urlEl.classList.add("validated");
    } else if (isGforms) {
      detectedDocsSource = "gforms";
      titleReady = true;
      urlEl.classList.add("validated");
    } else {
      detectedDocsSource = null;
      titleReady = false;
    }
    syncBtn();
    return;
  }

  titleReady = false;
  syncBtn();
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
      console.error("[info] failed for", url, data);
      setUrlError("Could not fetch video info. Make sure the file is a video and is publicly accessible.");
      return;
    }
    titleReady = true;
    urlEl.classList.add("validated");
    syncBtn();
  } catch (err) {
    console.error("[info] network error:", err);
    setUrlError("Network error — is the server running?");
  } finally {
    urlFetch.classList.remove("on");
    syncBtn();
  }
}

async function controlJob(action, jobId) {
  await fetch(`/${action}/${jobId}`, { method: "POST" });
}

document.getElementById("dl-form").addEventListener("submit", async (e) => {
  e.preventDefault();

  const url = getValidUrl(urlEl.value);
  if (!url) return;

  const effectiveSource = currentSource === "video" ? detectedVideoSource
                        : currentSource === "docs"  ? detectedDocsSource
                        : currentSource;
  const urlKey = effectiveSource === "gdrive" ? extractDriveId(url) : url;
  if (activeDownloads.has(urlKey)) { setUrlWarn("Already downloading"); return; }
  if (completedDownloads.has(urlKey)) { setUrlWarn("Already downloaded"); return; }
  setUrlWarn("");

  dlBtn.disabled = true;
  dlBtn.classList.add("loading");
  btnText.textContent = effectiveSource === "zoom" ? "Checking…" : "Starting…";

  const password = effectiveSource === "zoom"
    ? (document.getElementById("password-inp")?.value || "")
    : "";
  const result = await fetch("/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, threads: 16, chunk_size: 65536, source: effectiveSource, password }),
  })
    .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
    .catch((err) => { console.error("[start] network error:", err); return null; });

  dlBtn.classList.remove("loading");
  btnText.textContent = "Download";

  if (!result?.ok) {
    console.error("[start] failed:", result?.data);
    setUrlError(result?.data?.error || "Failed to start download. Is the server running?");
    syncBtn();
    return;
  }

  activeDownloads.add(urlKey);
  const card = createCard(result.data.job_id);
  card.dataset.urlKey   = urlKey;
  card.dataset.url      = url;
  card.dataset.source   = effectiveSource;
  card.dataset.password = password;
  trackJob(result.data.job_id, card, urlKey);

  updateDownloadsBadge();
  switchTab("downloads");
  resetForm();
});

syncBtn();
updateDownloadsEmpty();
loadHistory();
