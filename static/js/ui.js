let titleReady          = false;
let titleTimer          = null;
let _clearTimer         = null;
let currentSource       = "video";
let detectedVideoSource = null;
let detectedDocsSource  = null;

const activeDownloads    = new Set();
const completedDownloads = new Set();
const expiryTimers       = new Map();

const urlEl    = document.getElementById("url");
const dlBtn    = document.getElementById("dl-btn");
const btnText  = document.getElementById("btn-text");
const urlFetch = document.getElementById("url-fetch");
const urlError = document.getElementById("url-error");
const urlWarn  = document.getElementById("url-warn");
const clearBtn = document.querySelector(".history-clear-btn");

function getValidUrl(text) {
  const v = text.trim();
  if (currentSource === "video") return (isValidZoomUrl(v) || isValidDriveUrl(v)) ? v : null;
  if (currentSource === "docs")  return (isValidGdocsUrl(v) || isValidGformsUrl(v)) ? v : null;
  return null;
}

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("active", b.id === `tab-${name}`)
  );
  document.querySelectorAll(".tab-pane").forEach((p) =>
    p.classList.toggle("active", p.id === `pane-${name}`)
  );
}

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
  document.getElementById("password-inp").value = "";
  document.getElementById("password-row").style.display = "none";
  titleReady = false;
  setUrlError("");
  setUrlWarn("");
  syncBtn();
  urlEl.focus();
}

function togglePassword() {
  const inp = document.getElementById("password-inp");
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  document.getElementById("pw-eye").style.display     = show ? "none" : "";
  document.getElementById("pw-eye-off").style.display = show ? ""     : "none";
}

function setMode(mode) {
  const isFlashcard = mode === 'flashcard';
  document.getElementById('mode-downloads').style.display = isFlashcard ? 'none' : '';
  document.getElementById('mode-flashcard').style.display = isFlashcard ? '' : 'none';
  document.getElementById('modetab-downloads').classList.toggle('active', !isFlashcard);
  document.getElementById('modetab-flashcard').classList.toggle('active', isFlashcard);
  if (isFlashcard) fcInit();
}

function setSource(src) {
  currentSource       = src;
  detectedVideoSource = null;
  detectedDocsSource  = null;
  document.getElementById("src-video").classList.toggle("active", src === "video");
  document.getElementById("src-docs").classList.toggle("active", src === "docs");
  document.getElementById("password-row").style.display = "none";
  urlEl.placeholder =
    src === "docs" ? "Paste a Google Docs or Forms link" :
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
