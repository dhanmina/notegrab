// ── State ──

let fcQuestions = [];
let fcOrder     = [];
let fcIdx       = 0;
let fcOk        = 0;
let fcNo        = 0;
let fcAnswered  = false;

// ── DOM refs ──

const fcUrlInp    = document.getElementById('fc-url');
const fcAnsTA     = document.getElementById('fc-ans');
const fcLoadBtn   = document.getElementById('fc-load-btn');
const fcErrorEl   = document.getElementById('fc-error');
const fcInputWrap = document.getElementById('fc-input-wrap');
const fcLoadingEl = document.getElementById('fc-loading');
const fcStudyEl   = document.getElementById('fc-study');
const fcDoneEl    = document.getElementById('fc-done');

// ── Answer key helpers ──

function fcParseAnswers(raw) {
  return (raw || '').split('\n')
    .map(l => l.trim().toLowerCase())
    .filter(l => /^[a-d]$/.test(l));
}

function fcRefreshAnsCount() {
  const n  = fcParseAnswers(fcAnsTA.value).length;
  const el = document.getElementById('fc-ans-count');
  el.textContent = n > 0 ? `${n} entered` : '0 entered';
  el.className   = `fc-ans-count${n > 0 ? ' ready' : ''}`;
  fcSyncLoad();
}

function fcSyncLoad() {
  const urlOk = isValidGformsUrl((fcUrlInp.value || '').trim());
  const ansOk = fcParseAnswers(fcAnsTA.value).length > 0;
  const ok    = urlOk && ansOk;
  fcLoadBtn.classList.toggle('valid', ok);
  fcLoadBtn.disabled = !ok;
}

// ── Input listeners ──

fcUrlInp.addEventListener('input', () => {
  fcUrlInp.classList.toggle('validated', isValidGformsUrl(fcUrlInp.value.trim()));
  fcSetError('');
  fcSyncLoad();
});

fcAnsTA.addEventListener('input', () => {
  fcSetError('');
  fcRefreshAnsCount();
});

function fcSetError(msg) {
  fcErrorEl.textContent = msg;
  fcErrorEl.classList.toggle('on', !!msg);
}

// ── Load ──

async function fcLoad() {
  const url     = (fcUrlInp.value || '').trim();
  const answers = fcParseAnswers(fcAnsTA.value);

  if (!isValidGformsUrl(url)) return;
  if (answers.length === 0) { fcSetError('Enter the answer key (one letter per line).'); return; }

  fcLoadBtn.disabled = true;
  fcLoadBtn.classList.remove('valid');
  fcInputWrap.style.display = 'none';
  fcLoadingEl.style.display = '';
  fcSetError('');

  try {
    const r    = await fetch('/flashcard/parse', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ url }),
    });
    const data = await r.json();

    if (!r.ok || !data.questions) {
      fcInputWrap.style.display = '';
      fcSetError(data.error || 'Failed to load questions.');
      return;
    }

    const qs = data.questions;
    if (answers.length !== qs.length) {
      fcInputWrap.style.display = '';
      fcSetError(
        `Answer count mismatch: you entered ${answers.length} answer${answers.length !== 1 ? 's' : ''} ` +
        `but the form has ${qs.length} question${qs.length !== 1 ? 's' : ''}.`
      );
      return;
    }

    fcQuestions = qs.map((q, i) => ({ ...q, answer: answers[i].toUpperCase() }));
    fcBeginStudy(false);

  } catch {
    fcInputWrap.style.display = '';
    fcSetError('Network error — is the server running?');
  } finally {
    fcLoadingEl.style.display = 'none';
    if (fcInputWrap.style.display !== 'none') {
      fcLoadBtn.disabled = false;
      fcSyncLoad();
    }
  }
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

// ── Begin study session ──

function fcBeginStudy(keepOrder) {
  fcOrder    = keepOrder ? fcOrder : fcShuffle(fcQuestions.map((_, i) => i));
  fcIdx      = 0;
  fcOk       = 0;
  fcNo       = 0;
  fcAnswered = false;

  // Hide mode nav for focused study
  document.querySelector('.mode-nav').style.display = 'none';

  fcInputWrap.style.display = 'none';
  fcLoadingEl.style.display = 'none';
  fcDoneEl.style.display    = 'none';
  fcStudyEl.style.display   = '';

  fcRenderCard();
  fcSyncHeader();
}

// ── Render card ──

function fcRenderCard() {
  const q    = fcQuestions[fcOrder[fcIdx]];
  fcAnswered = false;

  document.getElementById('fc-qnum').textContent  = `Question ${q.num}`;
  document.getElementById('fc-qtext').textContent = q.text;

  // Hide next button
  const nextBtn = document.getElementById('fc-next-btn');
  nextBtn.style.display = 'none';

  // Build choice buttons
  const list = document.getElementById('fc-choices-list');
  list.innerHTML = '';

  for (const [ltr, txt] of Object.entries(q.choices)) {
    const btn = document.createElement('button');
    btn.className        = 'fc-choice-btn';
    btn.type             = 'button';
    btn.dataset.letter   = ltr;
    btn.innerHTML = `<span class="fc-choice-badge">${ltr}</span><span class="fc-choice-text">${esc(txt)}</span><span class="fc-choice-icon"></span>`;
    btn.addEventListener('click', () => fcPick(ltr));
    list.appendChild(btn);
  }

  // Scroll to top of study area on mobile
  fcStudyEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Pick an answer ──

function fcPick(picked) {
  if (fcAnswered) return;
  fcAnswered = true;

  const q       = fcQuestions[fcOrder[fcIdx]];
  const correct = q.answer;
  const isRight = picked === correct;

  if (isRight) fcOk++;
  else         fcNo++;

  // Apply visual states to all buttons
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

  // Show next / finish button
  const nextBtn  = document.getElementById('fc-next-btn');
  const isLast   = fcIdx === fcOrder.length - 1;
  nextBtn.textContent  = isLast ? 'See Results →' : 'Next →';
  nextBtn.style.display = '';
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

// ── Back to input ──

function fcExitStudy() {
  document.querySelector('.mode-nav').style.display = '';
  fcStudyEl.style.display   = 'none';
  fcDoneEl.style.display    = 'none';
  fcInputWrap.style.display = '';
  fcSyncLoad();
}

// ── Done screen ──

function fcShowDone() {
  const total = fcOrder.length;
  const pct   = total > 0 ? Math.round((fcOk / total) * 100) : 0;

  const pctEl = document.getElementById('fc-done-pct');
  pctEl.textContent = `${pct}%`;
  pctEl.className   = `fc-done-pct ${pct >= 80 ? 'great' : pct >= 60 ? 'ok' : 'bad'}`;
  document.getElementById('fc-done-label').textContent  = pct >= 80 ? 'Excellent!' : pct >= 60 ? 'Good effort!' : 'Keep studying!';
  document.getElementById('fc-done-ok').textContent     = `${fcOk} correct`;
  document.getElementById('fc-done-no').textContent     = `${fcNo} incorrect`;

  fcStudyEl.style.display = 'none';
  fcDoneEl.style.display  = '';
}

function fcDoShuffle() { fcBeginStudy(false); }
function fcDoRestart() { fcBeginStudy(true);  }

// ── Keyboard shortcuts (desktop) ──

document.addEventListener('keydown', (e) => {
  if (document.getElementById('mode-flashcard')?.style.display === 'none') return;
  if (fcStudyEl.style.display === 'none') return;
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
