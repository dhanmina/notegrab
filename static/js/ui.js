// ── Shared state ──

let titleReady   = false;
let titleTimer   = null;
let _clearTimer  = null;
let currentSource = "gdrive";

const activeDownloads    = new Set();
const completedDownloads = new Set();
const expiryTimers       = new Map();

// ── DOM refs ──

const urlEl    = document.getElementById("url");
const dlBtn    = document.getElementById("dl-btn");
const btnText  = document.getElementById("btn-text");
const urlFetch = document.getElementById("url-fetch");
const urlError = document.getElementById("url-error");
const urlWarn  = document.getElementById("url-warn");
const clearBtn = document.querySelector(".history-clear-btn");

// ── URL helpers ──

function getValidUrls(text) {
  if (currentSource === "zoom") {
    return text.split("\n").map((l) => l.trim()).filter((l) => isValidZoomUrl(l));
  }
  return text.split("\n").map((l) => l.trim()).filter((l) => isValidDriveUrl(l));
}

function isMultiMode() {
  return urlEl.value.split("\n").map((l) => l.trim()).filter(Boolean).length > 1;
}

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

// ── Button & input state ──

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

function setUrlError(msg) {
  urlError.textContent = msg;
  urlError.classList.toggle("on", !!msg);
  urlEl.classList.toggle("invalid", !!msg);
}

function setUrlWarn(msg) {
  urlWarn.textContent = msg;
  urlWarn.classList.toggle("on", !!msg);
}

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

// ── Source toggle ──

function setSource(src) {
  currentSource = src;
  document.getElementById("src-gdrive").classList.toggle("active", src === "gdrive");
  document.getElementById("src-zoom").classList.toggle("active", src === "zoom");
  document.getElementById("password-row").style.display = src === "zoom" ? "" : "none";
  urlEl.placeholder = src === "zoom" ? "Paste a Zoom recording link" : "Paste a Google Drive link";
  urlEl.value = "";
  urlEl.style.height = "";
  urlEl.classList.remove("validated", "invalid");
  titleReady = false;
  setUrlError("");
  setUrlWarn("");
  clearTimeout(titleTimer);
  syncBtn();
  urlEl.focus();
}
