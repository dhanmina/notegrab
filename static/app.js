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
  return text.split('\n').map(l => l.trim()).filter(l => isValidDriveUrl(l));
}

function isMultiMode() {
  return urlEl.value.split('\n').map(l => l.trim()).filter(Boolean).length > 1;
}

let titleReady = false;
let threads    = 4;
let driveExt   = '';
let titleTimer = null;

const activeDownloads    = new Set();
const completedDownloads = new Set();

const urlEl     = document.getElementById('url');
const dlBtn     = document.getElementById('dl-btn');
const btnText   = document.getElementById('btn-text');
const nameInp   = document.getElementById('output');
const extChip   = document.getElementById('ext-chip');
const urlFetch  = document.getElementById('url-fetch');
const urlError  = document.getElementById('url-error');
const urlWarn   = document.getElementById('url-warn');
const bottomRow = document.getElementById('bottom-row');
const nameField = document.getElementById('name-field');
const tVal      = document.getElementById('t-val');

function syncBtn() {
  const urls  = getValidUrls(urlEl.value);
  const multi = isMultiMode();
  const valid = multi ? urls.length > 0 : (urls.length > 0 && titleReady);
  dlBtn.classList.toggle('valid', valid);
  dlBtn.disabled = !valid;
  btnText.textContent = multi && urls.length > 1 ? `Download ${urls.length}` : 'Download';
}

function resizeTa() {
  urlEl.style.height = 'auto';
  urlEl.style.height = urlEl.scrollHeight + 'px';
}

function updateMode() {
  const multi = isMultiMode();
  nameField.style.display = multi ? 'none' : '';
  bottomRow.classList.toggle('threads-only', multi);
}

function setUrlError(msg) {
  urlError.textContent = msg;
  urlError.classList.toggle('on', !!msg);
  urlEl.classList.toggle('invalid', !!msg);
}

function setUrlWarn(msg) {
  urlWarn.textContent = msg;
  urlWarn.classList.toggle('on', !!msg);
}

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fmtB(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(2) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
  if (b >= 1e3) return (b / 1e3).toFixed(0) + ' KB';
  return b + ' B';
}

function fmtSpd(bps) {
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + ' MB/s';
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + ' KB/s';
  return bps + ' B/s';
}

function fmtEta(s) {
  if (!isFinite(s) || s <= 0) return '';
  if (s < 60)   return Math.ceil(s) + 's left';
  if (s < 3600) return Math.ceil(s / 60) + 'm left';
  return (s / 3600).toFixed(1) + 'h left';
}

document.getElementById('t-minus').addEventListener('click', () => {
  if (threads > 1) { threads--; tVal.textContent = threads; }
});
document.getElementById('t-plus').addEventListener('click', () => {
  if (threads < 16) { threads++; tVal.textContent = threads; }
});

urlEl.addEventListener('input', e => {
  clearTimeout(titleTimer);
  resizeTa();
  updateMode();
  setUrlError('');

  const v = e.target.value.trim();

  if (!v) {
    titleReady = false;
    driveExt   = '';
    nameInp.value              = '';
    nameInp.style.paddingRight = '16px';
    extChip.style.display      = 'none';
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
  urlFetch.classList.add('on');
  setUrlError('');
  try {
    const r    = await fetch('/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await r.json();
    if (!r.ok || !data.title) {
      setUrlError('Could not fetch video info. Make sure the file is a video and is publicly accessible.');
      return;
    }
    const dot  = data.title.lastIndexOf('.');
    driveExt   = dot !== -1 ? data.title.slice(dot) : '';
    const base = dot !== -1 ? data.title.slice(0, dot) : data.title;
    nameInp.value              = base;
    nameInp.style.paddingRight = driveExt ? '72px' : '16px';
    extChip.textContent        = driveExt;
    extChip.style.display      = driveExt ? '' : 'none';
    titleReady = true;
    syncBtn();
  } catch {
    setUrlError('Network error — is the server running?');
  } finally {
    urlFetch.classList.remove('on');
  }
}

async function controlJob(action, jobId) {
  await fetch(`/${action}/${jobId}`, { method: 'POST' });
}

function setCardActions(jobId, state, refs) {
  const act = refs.act;
  if (state === 'queued' || state === 'fetching') {
    act.innerHTML = `<button class="ctrl-btn stop-btn" onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === 'downloading') {
    act.innerHTML = `
      <button class="ctrl-btn pause-btn" onclick="controlJob('pause','${jobId}')">Pause</button>
      <button class="ctrl-btn stop-btn"  onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === 'paused') {
    act.innerHTML = `
      <button class="ctrl-btn resume-btn" onclick="controlJob('resume','${jobId}')">Resume</button>
      <button class="ctrl-btn stop-btn"   onclick="controlJob('stop','${jobId}')">Stop</button>`;
  } else if (state === 'done') {
    act.innerHTML = `
      <a class="save-btn" href="/download/${jobId}">Save file</a>
      <button class="dismiss-btn" onclick="dismissCard('${jobId}')">Dismiss</button>`;
  } else {
    act.innerHTML = `<button class="dismiss-btn" onclick="dismissCard('${jobId}')">Dismiss</button>`;
  }
}

function createCard(jobId) {
  const list = document.getElementById('downloads-list');
  const card = document.createElement('div');
  card.className = 'dl-card';
  card.id = `card-${jobId}`;
  card.innerHTML = `
    <div class="card-head">
      <div class="card-name" id="cname-${jobId}">—</div>
      <div class="card-tag"  id="ctag-${jobId}">Queued</div>
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
  }

  function markError(message) {
    finish();
    refs.tag.textContent = 'Error';
    refs.tag.classList.add('red');
    refs.pbar.className   = 'card-pbar-fill';
    refs.pbar.style.width = '0%';
    card.classList.add('error');
    card.insertAdjacentHTML('beforeend', `<div class="card-err-msg">${esc(message)}</div>`);
    setCardActions(jobId, 'error', refs);
  }

  const handlers = {
    queued() {
      refs.tag.textContent = 'Queued';
      setCardActions(jobId, 'queued', refs);
    },
    status(msg) {
      if (msg.message.startsWith('Downloading:')) {
        refs.tag.textContent  = 'Downloading';
        refs.name.textContent = msg.message.replace('Downloading: ', '');
        card.classList.remove('paused');
        setCardActions(jobId, 'downloading', refs);
      } else {
        refs.tag.textContent = msg.message;
        setCardActions(jobId, 'fetching', refs);
      }
    },
    progress(msg) {
      total = msg.total;
      const now = Date.now(), dt = (now - lt) / 1000, db = msg.downloaded - lb;
      if (dt > 0.3) {
        const bps = db / dt;
        const eta = bps > 0 && msg.total > 0 ? (msg.total - msg.downloaded) / bps : Infinity;
        refs.spd.textContent = fmtSpd(bps) + (eta < Infinity ? '  ·  ' + fmtEta(eta) : '');
        lb = msg.downloaded; lt = now;
      }
      if (msg.total > 0) {
        const pct = Math.min(100, (msg.downloaded / msg.total) * 100);
        refs.pbar.className   = 'card-pbar-fill';
        refs.pbar.style.width = pct.toFixed(1) + '%';
        refs.sz.textContent   = fmtB(msg.downloaded) + ' / ' + fmtB(msg.total);
      } else {
        refs.sz.textContent = fmtB(msg.downloaded);
      }
    },
    paused() {
      refs.tag.textContent = 'Paused';
      refs.spd.textContent = '';
      card.classList.add('paused');
      setCardActions(jobId, 'paused', refs);
    },
    resumed() {
      refs.tag.textContent = 'Downloading';
      card.classList.remove('paused');
      setCardActions(jobId, 'downloading', refs);
    },
    done(msg) {
      es.close();
      finish(true);
      refs.pbar.className   = 'card-pbar-fill';
      refs.pbar.style.width = '100%';
      refs.tag.textContent  = 'Done';
      refs.tag.classList.add('green');
      refs.name.textContent = msg.filename;
      refs.spd.textContent  = '';
      refs.sz.textContent   = [total ? fmtB(total) : '', ((Date.now() - t0) / 1000).toFixed(1) + 's'].filter(Boolean).join(' · ');
      card.classList.add('done');
      card.classList.remove('paused');
      setCardActions(jobId, 'done', refs);
    },
    error(msg) {
      es.close();
      markError(msg.message);
    },
    stopped() {
      es.close();
      finish();
      refs.tag.textContent  = 'Stopped';
      refs.spd.textContent  = '';
      refs.sz.textContent   = '';
      refs.pbar.className   = 'card-pbar-fill';
      refs.pbar.style.width = '0%';
      card.classList.add('stopped');
      card.classList.remove('paused');
      setCardActions(jobId, 'stopped', refs);
    },
  };

  es = new EventSource(`/progress/${jobId}`);

  es.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'ping') return;
    handlers[msg.type]?.(msg);
  };

  es.onerror = () => {
    if (finished) return;
    es.close();
    markError('Connection lost.');
  };
}

function dismissCard(jobId) {
  const card = document.getElementById(`card-${jobId}`);
  completedDownloads.delete(card?.dataset.driveId);
  fetch(`/delete/${jobId}`, { method: 'DELETE' });
  card?.remove();
}

function resetForm() {
  urlEl.value                = '';
  urlEl.style.height         = '';
  nameInp.value              = '';
  nameInp.style.paddingRight = '16px';
  extChip.style.display      = 'none';
  driveExt   = '';
  titleReady = false;
  setUrlError('');
  setUrlWarn('');
  updateMode();
  syncBtn();
  urlEl.focus();
}

document.getElementById('dl-form').addEventListener('submit', async e => {
  e.preventDefault();

  const allUrls = getValidUrls(urlEl.value);
  if (!allUrls.length) return;

  const isDupe = u => activeDownloads.has(extractDriveId(u)) || completedDownloads.has(extractDriveId(u));
  const dupes  = allUrls.filter(u => isDupe(u));
  const urls   = allUrls.filter(u => !isDupe(u));

  if (dupes.length) {
    const downloading = dupes.filter(u => activeDownloads.has(extractDriveId(u))).length;
    const downloaded  = dupes.filter(u => completedDownloads.has(extractDriveId(u))).length;
    const parts = [];
    if (downloading) parts.push(`${downloading} already downloading`);
    if (downloaded)  parts.push(`${downloaded} already downloaded`);
    setUrlWarn(`Skipped — ${parts.join(', ')}`);
  } else {
    setUrlWarn('');
  }

  if (!urls.length) {
    syncBtn();
    return;
  }

  const multi     = urls.length > 1;
  const base      = nameInp.value.trim();
  const outputVal = (!multi && base) ? base + driveExt : '';

  dlBtn.disabled = true;
  dlBtn.classList.add('loading');
  btnText.textContent = 'Starting…';

  const results = await Promise.all(urls.map(url =>
    fetch('/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, output: outputVal, threads, chunk_size: 65536 }),
    }).then(r => r.json().then(d => ({ ok: r.ok, data: d, url }))).catch(() => null)
  ));

  dlBtn.classList.remove('loading');
  btnText.textContent = 'Download';

  let anyStarted = false;
  for (const result of results) {
    if (!result || !result.ok) continue;
    const driveId = extractDriveId(result.url);
    activeDownloads.add(driveId);
    const card = createCard(result.data.job_id);
    card.dataset.driveId = driveId;
    trackJob(result.data.job_id, card, driveId);
    anyStarted = true;
  }

  if (!anyStarted) {
    setUrlError('Failed to start downloads. Is the server running?');
    syncBtn();
    return;
  }

  resetForm();
});

syncBtn();
