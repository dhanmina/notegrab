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
