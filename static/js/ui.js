// ── Shared state ──

let titleReady          = false;
let titleTimer          = null;
let _clearTimer         = null;
let currentSource       = "video";
let detectedVideoSource = null;

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

function getValidUrl(text) {
  const v = text.trim();
  if (currentSource === "video")  return (isValidZoomUrl(v) || isValidDriveUrl(v)) ? v : null;
  if (currentSource === "gdocs")  return isValidGdocsUrl(v)  ? v : null;
  if (currentSource === "gforms") return isValidGformsUrl(v) ? v : null;
  return null;
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
  const list    = document.getElementById("history-list");
  const empty   = document.getElementById("history-empty");
  const toolbar = document.querySelector(".history-toolbar");
  const hasItems = list.children.length > 0;
  if (empty)   empty.style.display   = hasItems ? "none" : "";
  if (toolbar) toolbar.style.display = hasItems ? ""     : "none";
}

// ── Button & input state ──

function syncBtn() {
  const valid = !!getValidUrl(urlEl.value) && titleReady;
  dlBtn.classList.toggle("valid", valid);
  dlBtn.disabled = !valid;
  if (!dlBtn.classList.contains("loading")) {
    btnText.textContent = "Download";
  }
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
  urlEl.classList.remove("validated");
  titleReady = false;
  setUrlError("");
  setUrlWarn("");
  syncBtn();
  urlEl.focus();
}

// ── Password toggle ──

function togglePassword() {
  const inp = document.getElementById("password-inp");
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  document.getElementById("pw-eye").style.display     = show ? "none" : "";
  document.getElementById("pw-eye-off").style.display = show ? ""     : "none";
}

// ── Mode switcher ──

function setMode(mode) {
  const isFlashcard = mode === 'flashcard';
  document.getElementById('mode-downloads').style.display = isFlashcard ? 'none' : '';
  document.getElementById('mode-flashcard').style.display = isFlashcard ? '' : 'none';
  document.getElementById('modetab-downloads').classList.toggle('active', !isFlashcard);
  document.getElementById('modetab-flashcard').classList.toggle('active', isFlashcard);
  if (isFlashcard) fcInit();
}

// ── Source toggle ──

function setSource(src) {
  currentSource       = src;
  detectedVideoSource = null;
  document.getElementById("src-video").classList.toggle("active", src === "video");
  document.getElementById("src-gdocs").classList.toggle("active", src === "gdocs");
  document.getElementById("src-gforms").classList.toggle("active", src === "gforms");
  document.getElementById("password-row").style.display = "none";
  urlEl.placeholder =
    src === "gdocs"  ? "Paste a Google Docs link" :
    src === "gforms" ? "Paste a Google Forms link" :
                       "Paste a Google Drive or Zoom link";
  urlEl.value = "";
  urlEl.classList.remove("validated", "invalid");
  titleReady = false;
  setUrlError("");
  setUrlWarn("");
  clearTimeout(titleTimer);
  syncBtn();
  urlEl.focus();
}
