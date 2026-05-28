import re
import logging

from .forms import extract_form_id, _download_html, _load_public_data, _norm_title, _is_skipped_title

log = logging.getLogger(__name__)

_Q_NUM_RE   = re.compile(r'^(\d{1,3})[.)\s\xa0]+(.+)', re.DOTALL | re.S)
_CHOICE_RE  = re.compile(r'^([A-Da-d])[.)]\s*(.*)', re.DOTALL | re.S)


def extract_questions(url: str) -> list[dict]:
    form_id = extract_form_id(url)
    if not form_id:
        raise ValueError('Could not extract form ID from URL')

    html = _download_html(url)
    data = _load_public_data(html)

    form = data[1]
    questions = []

    for raw in (form[1] or []):
        title_text = _norm_title(raw[1] if len(raw) > 1 else '')
        if not title_text or _is_skipped_title(title_text):
            continue

        item_type = raw[3] if len(raw) > 3 else None
        if item_type == 6:
            continue

        entries = raw[4] if len(raw) > 4 and isinstance(raw[4], list) else []
        if not entries:
            continue
        raw_choices = entries[0][1] if len(entries[0]) > 1 and isinstance(entries[0][1], list) else []
        if len(raw_choices) < 2:
            continue

        choices = {}
        for choice in raw_choices:
            if not choice:
                continue
            ct = _norm_title(choice[0])
            m = _CHOICE_RE.match(ct)
            if m:
                choices[m.group(1).upper()] = m.group(2).strip()

        if len(choices) < 2:
            continue

        q_match = _Q_NUM_RE.match(title_text)
        num   = int(q_match.group(1))   if q_match else len(questions) + 1
        qtext = q_match.group(2).strip() if q_match else title_text

        questions.append({
            'num':     num,
            'text':    qtext,
            'choices': choices,
            'answer':  None,
        })

    log.info('Extracted %d questions from form %s', len(questions), form_id)
    return questions[:100]
