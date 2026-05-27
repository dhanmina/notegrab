import io
import json
import logging
import re
from pathlib import Path

import requests
from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Pt

from .builder import convert as convert_doc_template
from .styles import clean, style_run

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_URL = 'https://docs.google.com/document/d/1S02noSARXsm5hsHUfGO_Rpccq5td_1fe/edit'
DEFAULT_TEMPLATE_DOCX = Path(__file__).resolve().parent / 'assets' / 'exam_template.docx'
_FORM_DATA_RE = re.compile(r'var FB_PUBLIC_LOAD_DATA_ = (.*?);</script>', re.S)
_FORM_ID_RE = re.compile(r'/forms/d/e/([^/]+)|/forms/d/([^/]+)')
_SKIP_TITLES = {
    'email',
    'full name (surname, first name, middle name)',
    'complete name of school',
    'branch',
    'block',
    'branch & block',
    'branch and block',
    'branch/block',
}


def is_form_url(url: str) -> bool:
    return 'docs.google.com/forms/' in url


def extract_form_id(url: str) -> str | None:
    m = _FORM_ID_RE.search(url.strip())
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _download_html(url: str) -> str:
    log.info('Downloading Google Form from %s', url)
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    return r.text


def _load_public_data(html: str) -> list:
    m = _FORM_DATA_RE.search(html)
    if not m:
        raise ValueError('No Google Forms data found. The form may be private or inaccessible.')
    return json.loads(m.group(1))


def _norm_title(text: str | None) -> str:
    return clean(text or '').strip().rstrip('*').strip()


def _is_skipped_title(title: str) -> bool:
    compact = re.sub(r'\s+', ' ', title).strip().lower()
    if compact in _SKIP_TITLES:
        return True
    return bool(re.fullmatch(r'(branch|block)(\s*[/&-]\s*|\s+and\s+)(branch|block)', compact))


def _extract_choices(item: list) -> list[str]:
    entries = item[4] if len(item) > 4 and isinstance(item[4], list) else []
    if not entries:
        return []
    raw_choices = entries[0][1] if len(entries[0]) > 1 and isinstance(entries[0][1], list) else []
    return [_norm_title(choice[0]) for choice in raw_choices if choice and _norm_title(choice[0])]


def _extract_items(data: list) -> tuple[str, list[dict]]:
    form = data[1]
    title = _norm_title(form[8] if len(form) > 8 else '') or 'Google Form'
    items = []

    for raw in form[1] or []:
        title_text = _norm_title(raw[1] if len(raw) > 1 else '')
        if not title_text or _is_skipped_title(title_text):
            continue

        item_type = raw[3] if len(raw) > 3 else None
        if item_type == 6:
            items.append({'type': 'section', 'text': title_text})
            continue

        choices = _extract_choices(raw)
        if choices:
            items.append({'type': 'question', 'text': title_text, 'choices': choices})

    return title, items


def _style_paragraph(p, *, font_size: int = 9, bold: bool = False) -> None:
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    for run in p.runs:
        style_run(run, {'ts_ff': 'Tahoma', 'ts_fs': font_size, 'ts_bd': bold})


def _title_lines(title: str) -> list[str]:
    m = re.search(r'recalls?\s*(\d+)\s+examinations?.*?\bNP\s*([IVX0-9]+)', title, re.I)
    if not m:
        m = re.search(r'recalls?\s+examinations?\s*(\d+).*?\bNP\s*([IVX0-9]+)', title, re.I)
    if not m:
        return [title]
    exam_no, practice = m.groups()
    practice = {'1': 'I', '2': 'II', '3': 'III', '4': 'IV', '5': 'V'}.get(practice, practice)
    return [
        f'RECALLS {exam_no} EXAMINATIONS',
        f'NURSING PRACTICE {practice}',
        'COMMUNITY HEALTH NURSING',
    ]


def _replace_template_title(doc, title: str) -> None:
    if len(doc.paragraphs) < 2:
        return
    p = doc.paragraphs[1]
    p.clear()
    lines = _title_lines(title)
    for i, line in enumerate(lines):
        if i:
            p.add_run().add_break()
        r = p.add_run(line)
        style_run(r, {'ts_ff': 'Tahoma', 'ts_fs': 16, 'ts_bd': True})
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE


def _first_question_paragraph_index(doc) -> int:
    for idx, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if idx > 2 and re.match(r'^(Situation[:\s]|Situation\s*\d+)', text, re.I):
            return idx
    return min(len(doc.paragraphs), 9)


def _remove_template_questions(doc) -> None:
    keep_until = _first_question_paragraph_index(doc)
    for p in list(doc.paragraphs[keep_until:]):
        p._element.getparent().remove(p._element)


def _load_template_doc(template_url: str | None) -> Document:
    if template_url is None and DEFAULT_TEMPLATE_DOCX.exists():
        return Document(DEFAULT_TEMPLATE_DOCX)

    template_bytes, _ = convert_doc_template(template_url or DEFAULT_TEMPLATE_URL)
    return Document(io.BytesIO(template_bytes))


def _add_section(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.add_run(text)
    _style_paragraph(p, font_size=9, bold=True)


def _add_question(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(18)
    p.paragraph_format.first_line_indent = Pt(-18)
    text = re.sub(r'^(\d{1,3}\.)([ \t\xa0]*)(\S)', r'\1\t\3', text, count=1)
    p.add_run(text)
    _style_paragraph(p, font_size=9)


def _add_choice(doc, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(36)
    p.paragraph_format.first_line_indent = Pt(-18)
    text = re.sub(r'^([A-D]\.)([ \t\xa0]*)(\S)', r'\1\t\3', text, count=1)
    p.add_run(text)
    _style_paragraph(p, font_size=9)


def build_docx(title: str, items: list[dict], template_url: str | None = None) -> bytes:
    doc = _load_template_doc(template_url)
    _replace_template_title(doc, title)
    _remove_template_questions(doc)

    for item in items:
        if item['type'] == 'section':
            _add_section(doc, item['text'])
        elif item['type'] == 'question':
            _add_question(doc, item['text'])
            for choice in item['choices']:
                _add_choice(doc, choice)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def convert(url: str, template_url: str | None = None) -> tuple[bytes, str]:
    html = _download_html(url)
    data = _load_public_data(html)
    title, items = _extract_items(data)
    if not items:
        raise ValueError('No quiz items found in the Google Form.')
    log.info('Parsed Google Form: %s (%d output items)', title, len(items))
    return build_docx(title, items, template_url=template_url), title
