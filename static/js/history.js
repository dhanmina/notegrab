function renderHistoryEntry(entry) {
  const el = document.createElement("div");
  el.className = "history-entry";
  el.id = `hentry-${entry.id}`;
  const redownloadBtn = entry.url
    ? `<button class="history-redl" title="Re-download" onclick="redownload('${esc(entry.url)}','${esc(entry.source || '')}')">↓</button>`
    : '';
  el.innerHTML = `
    <div class="history-name" title="${esc(entry.filename)}">${esc(midTrunc(entry.filename))}</div>
    <div class="history-meta">${entry.size ? fmtB(entry.size) + " · " : ""}${fmtDate(entry.downloaded_at)}</div>
    ${redownloadBtn}
    <button class="history-del" onclick="deleteHistoryEntry('${entry.id}')">×</button>
  `;
  return el;
}

async function redownload(url, source) {
  const result = await fetch("/start", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ url, source, threads: 16, chunk_size: 65536, password: "" }),
  }).then((r) => r.json().then((d) => ({ ok: r.ok, data: d }))).catch(() => null);

  if (!result?.ok) {
    alert(result?.data?.error || "Failed to start download.");
    return;
  }

  const urlKey = source === "gdrive" ? extractDriveId(url) : url;
  activeDownloads.add(urlKey);
  const card = createCard(result.data.job_id);
  card.dataset.urlKey = urlKey;
  card.dataset.url    = url;
  card.dataset.source = source;
  trackJob(result.data.job_id, card, urlKey);
  updateDownloadsBadge();

  document.getElementById("mode-downloads").style.display = "";
  document.getElementById("mode-flashcard").style.display = "none";
  document.getElementById("modetab-downloads").classList.add("active");
  document.getElementById("modetab-flashcard").classList.remove("active");
  switchTab("downloads");
}

async function loadHistory() {
  const entries = await fetch("/history").then((r) => r.json()).catch(() => []);
  const list = document.getElementById("history-list");
  list.innerHTML = "";
  entries.forEach((e) => list.appendChild(renderHistoryEntry(e)));
  updateHistoryEmpty();
}

function prependHistoryEntry(entry) {
  const list = document.getElementById("history-list");
  list.insertBefore(renderHistoryEntry(entry), list.firstChild);
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
