// ── State ──

let fcSets       = [];
let fcLoaded     = false;
let fcCurrentSet = null;
let fcEditingId  = null;
let fcSearchQ    = '';

let fcQuestions = [];
let fcOrder     = [];
let fcWrong     = [];
let fcIdx       = 0;
let fcOk        = 0;
let fcNo        = 0;
let fcAnswered  = false;

// ── Screen management ──

function fcShow(screenId) {
  ['fc-home', 'fc-form-wrap', 'fc-loading', 'fc-study', 'fc-done'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = id === screenId ? '' : 'none';
  });
  const nav = document.querySelector('.mode-nav');
  if (nav) nav.style.display = screenId === 'fc-study' ? 'none' : '';
}

// ── Init ──

async function fcInit() {
  if (fcLoaded) {
    fcRenderHome();
    fcShow('fc-home');
    return;
  }
  fcShow('fc-loading');
  try {
    const r = await fetch('/flashcards');
    const d = await r.json();
    fcSets  = Array.isArray(d) ? d : [];
    fcLoaded = true;
  } catch {
    fcSets = [];
  }
  fcRenderHome();
  fcShow('fc-home');
}

// ── Home ──

function fcOnSearch(q) {
  fcSearchQ = q;
  fcRenderHome();
}

function fcRenderHome() {
  const q        = fcSearchQ.trim().toLowerCase();
  const filtered = q ? fcSets.filter(s => s.title.toLowerCase().includes(q)) : fcSets;
  const grid     = document.getElementById('fc-grid');
  const empty    = document.getElementById('fc-home-empty');

  if (filtered.length === 0) {
    grid.innerHTML      = '';
    empty.style.display = '';
  } else {
    empty.style.display = 'none';
    grid.innerHTML      = filtered.map(fcCardHTML).join('');
  }
}

function fcCardHTML(s) {
  const count = (s.questions || []).length;
  const date  = s.updated_at
    ? new Date(s.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : '';
  const id = s.id;
  return `
    <div class="fc-card" data-id="${id}">
      <div class="fc-card-body">
        <div class="fc-card-title">${esc(s.title)}</div>
        <div class="fc-card-meta">${count} question${count !== 1 ? 's' : ''} · ${date}</div>
      </div>
      <div class="fc-card-actions">
        <button class="fc-card-study" type="button" onclick="fcStudySet('${id}')">Study</button>
        <button class="fc-card-action" type="button" onclick="fcShowForm('${id}')" title="Edit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="fc-card-action" type="button" onclick="fcDownloadSet('${id}')" title="Download backup">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
        <button class="fc-card-action danger" type="button" onclick="fcDeleteSet('${id}')" title="Delete">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
        </button>
      </div>
    </div>`;
}

// ── Create / Edit form ──

function fcShowForm(id) {
  fcEditingId = id || null;
  const heading  = document.getElementById('fc-form-heading');
  const titleInp = document.getElementById('fc-title');
  const urlInp   = document.getElementById('fc-url');

  fcSetError('');
  fcInitAnswerGrid();
  fcInitPasteStrip();

  const urlRow = document.getElementById('fc-url-row');
  if (id) {
    const s = fcSets.find(x => x.id === id);
    if (!s) return;
    heading.textContent = 'Edit Set';
    titleInp.value      = s.title || '';
    fcExpectedCount     = (s.questions || []).length;
    if (urlRow) urlRow.style.display = 'none';
    fcFillAnswers(s.answers || '');
  } else {
    heading.textContent = 'New Set';
    titleInp.value      = '';
    urlInp.value        = '';
    fcExpectedCount     = 0;
    urlInp.classList.remove('validated');
    if (urlRow) urlRow.style.display = '';
  }

  fcRefreshAnsCount();
  fcSyncSave();
  fcShow('fc-form-wrap');
}

function fcCancelForm() {
  fcShow('fc-home');
}

function fcOnUrlInput() {
  const urlInp = document.getElementById('fc-url');
  urlInp.classList.toggle('validated', isValidGformsUrl(urlInp.value.trim()));
  fcSetError('');
  fcSyncSave();
}

// ── Answer key grid ──

let fcActiveCell    = -1;
let fcExpectedCount = 0;

function fcCell(idx) {
  return document.getElementById(`fc-cell-${idx}`);
}

function fcInitAnswerGrid() {
  const grid = document.getElementById('fc-ans-grid');
  if (!grid) return;
  let html = '';
  for (let i = 0; i < 100; i++) {
    if (i > 0 && i % 25 === 0) html += `<div class="fc-ans-sep"></div>`;
    html += `<button class="fc-ans-cell" id="fc-cell-${i}" type="button"
               data-idx="${i}" data-value="" onclick="fcFocusCell(${i})">
               <span class="fc-ans-num">${i + 1}</span>
               <span class="fc-ans-val"></span>
             </button>`;
  }
  grid.innerHTML = html;
  fcActiveCell = -1;
}

function fcFocusCell(idx) {
  if (fcActiveCell >= 0) fcCell(fcActiveCell)?.classList.remove('active');
  fcActiveCell = idx;
  fcCell(idx)?.classList.add('active');
  const kb = document.getElementById('fc-kb-inp');
  if (kb) { kb.value = ''; kb.focus(); }
}

function fcSetCellValue(idx, val) {
  const cell = fcCell(idx);
  if (!cell) return;
  cell.dataset.value = val;
  cell.querySelector('.fc-ans-val').textContent = val;
  cell.classList.toggle('filled', !!val);
}

function fcKbInput(input) {
  const val = input.value.replace(/[^a-dA-D]/g, '').toUpperCase().slice(-1);
  input.value = '';
  if (!val || fcActiveCell < 0) return;
  fcSetCellValue(fcActiveCell, val);
  fcRefreshAnsCount();
  const next = fcActiveCell + 1;
  if (next < 100) fcFocusCell(next);
  else { fcCell(fcActiveCell)?.classList.remove('active'); fcActiveCell = -1; }
}

function fcKbKey(e) {
  const idx = fcActiveCell;
  if (e.key === 'Backspace') {
    e.preventDefault();
    if (idx < 0) return;
    if (fcCell(idx)?.dataset.value) {
      fcSetCellValue(idx, ''); fcRefreshAnsCount();
    } else if (idx > 0) {
      fcFocusCell(idx - 1);
      fcSetCellValue(idx - 1, ''); fcRefreshAnsCount();
    }
  }
  if (e.key === 'Escape') { fcCell(idx)?.classList.remove('active'); fcActiveCell = -1; document.getElementById('fc-kb-inp')?.blur(); }
  if (e.key === 'ArrowRight' && idx < 99)      { e.preventDefault(); fcFocusCell(idx + 1); }
  if (e.key === 'ArrowLeft'  && idx > 0)       { e.preventDefault(); fcFocusCell(idx - 1); }
  if (e.key === 'ArrowDown'  && idx + 5 < 100) { e.preventDefault(); fcFocusCell(idx + 5); }
  if (e.key === 'ArrowUp'    && idx - 5 >= 0)  { e.preventDefault(); fcFocusCell(idx - 5); }
}

function fcKbBlur() {
  setTimeout(() => {
    if (document.activeElement?.id !== 'fc-kb-inp') {
      fcCell(fcActiveCell)?.classList.remove('active');
      fcActiveCell = -1;
    }
  }, 200);
}

// Paste strip — paste event fills from position 0 (full replace); typing fills from first empty cell
function fcInitPasteStrip() {
  const input = document.getElementById('fc-paste-inp');
  if (!input || input._fcInited) return;
  input._fcInited = true;

  input.addEventListener('paste', (e) => {
    e.preventDefault();
    const raw     = (e.clipboardData || window.clipboardData).getData('text');
    const cleaned = raw.replace(/[^a-dA-D]/g, '').toUpperCase().slice(0, 100);

    if (fcEditingId && fcExpectedCount > 0) {
      if (cleaned.length !== fcExpectedCount) {
        fcSetError(`Expected ${fcExpectedCount} answers, got ${cleaned.length}. Nothing changed.`);
        input.value = '';
        return;
      }
      fcSetError('');
      input.value = '';
      fcShowReplaceModal(cleaned);
      return;
    }

    fcFillGridFrom(cleaned, 0);
    input.value = '';
    fcRefreshAnsCount();
  });
}

function fcFillGridFrom(letters, startIdx) {
  [...letters].forEach((l, i) => {
    const t = startIdx + i;
    if (t >= 100) return;
    fcSetCellValue(t, l);
  });
}

function fcHandlePasteStrip(input) {
  const limit   = fcEditingId && fcExpectedCount > 0 ? fcExpectedCount : 100;
  const cleaned = input.value.replace(/[^a-dA-D]/g, '').toUpperCase().slice(0, limit);
  input.value   = cleaned;

  if (fcEditingId && fcExpectedCount > 0) {
    // In edit mode: accumulate silently, only act when count matches
    if (cleaned.length === fcExpectedCount) {
      fcSetError('');
      input.value = '';
      fcShowReplaceModal(cleaned);
    }
    return;
  }

  // Create mode: fill from first empty cell
  if (!cleaned.length) return;
  const cells    = [...document.querySelectorAll('.fc-ans-cell[data-idx]')];
  const from     = cells.findIndex(c => !c.dataset.value);
  const startIdx = from === -1 ? 0 : from;
  fcFillGridFrom(cleaned, startIdx);
  input.value = '';
  fcRefreshAnsCount();
}

function fcShowReplaceModal(answers) {
  const modal = document.getElementById('fc-replace-modal');
  const body  = document.getElementById('fc-modal-body');
  body.textContent = `This will overwrite all ${answers.length} answers.`;
  document.getElementById('fc-paste-inp')?.blur();
  modal.style.display = '';

  document.getElementById('fc-modal-yes').onclick = () => {
    modal.style.display = 'none';
    fcFillGridFrom(answers, 0);
    fcRefreshAnsCount();
  };
  document.getElementById('fc-modal-no').onclick = () => {
    modal.style.display = 'none';
  };
}

function fcClearAllAnswers() {
  for (let i = 0; i < 100; i++) fcSetCellValue(i, '');
  fcRefreshAnsCount();
}

function fcFillAnswers(raw) {
  const letters = (raw || '').toUpperCase().match(/[A-D]/g) || [];
  for (let i = 0; i < 100; i++) fcSetCellValue(i, letters[i] || '');
}

function fcGetAnswersRaw() {
  return Array.from({ length: 100 }, (_, i) => fcCell(i)?.dataset.value?.toLowerCase() || '')
    .filter(v => /^[a-d]$/.test(v))
    .join('\n');
}

function fcParseAnswers() {
  return Array.from({ length: 100 }, (_, i) => fcCell(i)?.dataset.value?.toLowerCase() || '')
    .filter(v => /^[a-d]$/.test(v));
}

function fcRefreshAnsCount() {
  const n  = fcParseAnswers().length;
  const el = document.getElementById('fc-ans-count');
  el.textContent = `${n} / 100`;
  el.className   = `fc-ans-count${n > 0 ? ' ready' : ''}`;
  fcSyncSave();
}

function fcSyncSave() {
  const titleOk = (document.getElementById('fc-title').value || '').trim().length > 0;
  const urlOk   = fcEditingId ? true : isValidGformsUrl((document.getElementById('fc-url').value || '').trim());
  const ansOk   = fcParseAnswers().length > 0;
  const ok      = titleOk && urlOk && ansOk;
  const btn     = document.getElementById('fc-save-btn');
  btn.classList.toggle('valid', ok);
  btn.disabled = !ok;
}

function fcSetError(msg) {
  const el = document.getElementById('fc-error');
  el.textContent = msg;
  el.classList.toggle('on', !!msg);
}

async function fcSaveForm() {
  const title      = (document.getElementById('fc-title').value || '').trim();
  const url        = (document.getElementById('fc-url').value || '').trim();
  const answersRaw = fcGetAnswersRaw();

  if (!title || (!fcEditingId && !url) || fcParseAnswers().length === 0) return;

  const btn    = document.getElementById('fc-save-btn');
  const spinEl = document.getElementById('fc-save-spin');
  const textEl = document.getElementById('fc-save-text');

  btn.disabled         = true;
  btn.classList.remove('valid');
  spinEl.style.display = '';
  textEl.textContent   = 'Saving…';
  fcSetError('');

  try {
    let r, data;
    if (fcEditingId) {
      r = await fetch(`/flashcards/${fcEditingId}`, {
        method:  'PUT',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ title, url, answers: answersRaw }),
      });
    } else {
      r = await fetch('/flashcards', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ title, url, answers: answersRaw }),
      });
    }
    data = await r.json();

    if (!r.ok) {
      fcSetError(data.error || 'Failed to save.');
      return;
    }

    if (fcEditingId) {
      fcSets = fcSets.map(s => s.id === fcEditingId ? data : s);
    } else {
      fcSets.unshift(data);
    }

    fcRenderHome();
    fcShow('fc-home');

  } catch {
    fcSetError('Network error — is the server running?');
  } finally {
    spinEl.style.display = 'none';
    textEl.textContent   = 'Save';
    btn.disabled         = false;
    fcSyncSave();
  }
}

// ── Study ──

function fcStudySet(id) {
  const s = fcSets.find(x => x.id === id);
  if (!s || !s.questions || s.questions.length === 0) return;
  fcCurrentSet = s;
  fcQuestions  = s.questions;
  fcBeginStudy(false);
}

function fcBeginStudy(keepOrder) {
  fcOrder    = keepOrder ? fcOrder : fcShuffle(fcQuestions.map((_, i) => i));
  fcIdx      = 0;
  fcOk       = 0;
  fcNo       = 0;
  fcWrong    = [];
  fcAnswered = false;

  fcShow('fc-study');
  fcRenderCard();
  fcSyncHeader();
}

function fcExitStudy() {
  fcCurrentSet = null;
  fcShow('fc-home');
}

function fcEditCurrentSet() {
  const id = fcCurrentSet ? fcCurrentSet.id : null;
  fcCurrentSet = null;
  if (id) fcShowForm(id);
  else    fcShow('fc-home');
}

// ── Render card ──

function fcRenderCard() {
  const q    = fcQuestions[fcOrder[fcIdx]];
  fcAnswered = false;

  document.getElementById('fc-qnum').textContent  = `Question ${q.num}`;
  document.getElementById('fc-qtext').textContent = q.text;

  const nextBtn = document.getElementById('fc-next-btn');
  nextBtn.disabled    = true;
  nextBtn.textContent = 'Next →';

  const list = document.getElementById('fc-choices-list');
  list.innerHTML = '';

  for (const [ltr, txt] of Object.entries(q.choices)) {
    const btn = document.createElement('button');
    btn.className      = 'fc-choice-btn';
    btn.type           = 'button';
    btn.dataset.letter = ltr;
    btn.innerHTML = `<span class="fc-choice-badge">${ltr}</span><span class="fc-choice-text">${esc(txt)}</span><span class="fc-choice-icon"></span>`;
    btn.addEventListener('click', () => fcPick(ltr));
    list.appendChild(btn);
  }

  const qZone = document.getElementById('fc-study').querySelector('.fc-q-zone');
  if (qZone) qZone.scrollTop = 0;
}

// ── Pick ──

function fcPick(picked) {
  if (fcAnswered) return;
  fcAnswered = true;

  const q       = fcQuestions[fcOrder[fcIdx]];
  const correct = q.answer;
  const isRight = picked === correct;

  if (isRight) fcOk++;
  else       { fcNo++; fcWrong.push(fcOrder[fcIdx]); }

  document.querySelectorAll('.fc-choice-btn').forEach(btn => {
    btn.disabled = true;
    const ltr  = btn.dataset.letter;
    const icon = btn.querySelector('.fc-choice-icon');
    if (ltr === correct) {
      btn.classList.add('state-correct');
      icon.textContent = '✓';
    } else if (ltr === picked) {
      btn.classList.add('state-wrong');
      icon.textContent = '✗';
    } else {
      btn.classList.add('state-dim');
    }
  });

  fcSyncHeader();

  const nextBtn = document.getElementById('fc-next-btn');
  nextBtn.textContent = fcIdx === fcOrder.length - 1 ? 'See Results →' : 'Next →';
  nextBtn.disabled    = false;
}

// ── Advance ──

function fcNext() {
  if (fcIdx < fcOrder.length - 1) {
    fcIdx++;
    fcRenderCard();
    fcSyncHeader();
  } else {
    fcShowDone();
  }
}

// ── Header sync ──

function fcSyncHeader() {
  const total   = fcOrder.length;
  const current = Math.min(fcIdx + 1, total);
  document.getElementById('fc-counter').textContent   = `${current} / ${total}`;
  document.getElementById('fc-prog-fill').style.width = `${(current / total) * 100}%`;
  document.getElementById('fc-score-ok').textContent  = fcOk;
  document.getElementById('fc-score-no').textContent  = fcNo;
}

// ── Done ──

function fcShowDone() {
  const total = fcOrder.length;
  const pct   = total > 0 ? Math.round((fcOk / total) * 100) : 0;

  const pctEl = document.getElementById('fc-done-pct');
  pctEl.textContent = `${pct}%`;
  pctEl.className   = `fc-done-pct ${pct >= 80 ? 'great' : pct >= 60 ? 'ok' : 'bad'}`;

  document.getElementById('fc-done-label').textContent = pct >= 80 ? 'Excellent!' : pct >= 60 ? 'Good effort!' : 'Keep studying!';
  document.getElementById('fc-done-ok').textContent    = `${fcOk} correct`;
  document.getElementById('fc-done-no').textContent    = `${fcNo} incorrect`;

  const wrongBtn = document.getElementById('fc-wrong-btn');
  if (wrongBtn) wrongBtn.style.display = fcWrong.length > 0 ? '' : 'none';

  document.getElementById('fc-study').style.display = 'none';
  document.getElementById('fc-done').style.display  = '';
}

function fcDoShuffle()   { fcBeginStudy(false); }
function fcDoRestart()   { fcBeginStudy(true);  }
function fcDoWrongOnly() {
  if (fcWrong.length === 0) return;
  const wrongIndices = [...fcWrong];
  fcOrder    = fcShuffle(wrongIndices);
  fcIdx      = 0;
  fcOk       = 0;
  fcNo       = 0;
  fcWrong    = [];
  fcAnswered = false;
  fcShow('fc-study');
  fcRenderCard();
  fcSyncHeader();
}

// ── Shuffle ──

function fcShuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ── Download ──

function fcDownloadSet(id) {
  const s = fcSets.find(x => x.id === id);
  if (!s) return;
  const backup = {
    id:         s.id,
    title:      s.title,
    url:        s.url,
    answers:    s.answers,
    questions:  s.questions,
    created_at: s.created_at,
    updated_at: s.updated_at,
  };
  const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = `${s.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_flashcards.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Upload / Import ──

function fcTriggerUpload() {
  const inp = document.getElementById('fc-file-inp');
  inp.value = '';
  inp.click();
}

async function fcHandleUpload(input) {
  const file = input.files[0];
  if (!file) return;

  let setData;
  try {
    setData = JSON.parse(await file.text());
  } catch {
    alert('Invalid JSON file.');
    return;
  }

  if (!setData.id || !setData.title) {
    alert('Invalid backup — missing id or title.');
    return;
  }

  const r = await fetch('/flashcards/import', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ set: setData, force: false }),
  });

  if (r.status === 409) {
    const d  = await r.json();
    const ok = confirm(`"${d.title}" already exists. Replace it with this backup?`);
    if (!ok) return;

    const r2 = await fetch('/flashcards/import', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ set: setData, force: true }),
    });
    const d2 = await r2.json();
    if (!r2.ok) { alert(d2.error || 'Import failed.'); return; }
    fcSets = fcSets.map(s => s.id === setData.id ? d2.entry : s);
  } else if (r.ok) {
    const d = await r.json();
    fcSets.unshift(d.entry);
  } else {
    const d = await r.json();
    alert(d.error || 'Import failed.');
    return;
  }

  fcRenderHome();
}

// ── Delete ──

async function fcDeleteSet(id) {
  const s = fcSets.find(x => x.id === id);
  if (!s) return;
  if (!confirm(`Delete "${s.title}"?`)) return;

  await fetch(`/flashcards/${id}`, { method: 'DELETE' });
  fcSets = fcSets.filter(x => x.id !== id);
  fcRenderHome();
}

// ── Keyboard shortcuts ──

document.addEventListener('keydown', (e) => {
  if (document.getElementById('mode-flashcard')?.style.display === 'none') return;
  if (document.getElementById('fc-study')?.style.display === 'none') return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  if (!fcAnswered) {
    const map = { a: 'A', b: 'B', c: 'C', d: 'D' };
    if (map[e.key.toLowerCase()]) { e.preventDefault(); fcPick(map[e.key.toLowerCase()]); return; }
  }
  if (fcAnswered && (e.code === 'Enter' || e.code === 'ArrowRight')) {
    e.preventDefault();
    fcNext();
  }
});
