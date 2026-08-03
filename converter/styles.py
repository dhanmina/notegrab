import re
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

ALIGN_MAP = {
    0: WD_ALIGN_PARAGRAPH.LEFT,
    1: WD_ALIGN_PARAGRAPH.CENTER,
    2: WD_ALIGN_PARAGRAPH.RIGHT,
    3: WD_ALIGN_PARAGRAPH.JUSTIFY,
}
TAB_ALIGN_MAP = {0: 'left', 1: 'center', 2: 'right', 3: 'decimal'}

CLEAN_RE = re.compile(
    r'[^\x09\x20-\x7E\xA0-\uD7FF\uF900-\uFDFF\uFE10-\uFFEF]'
)

_NBSP_RUN_RE = re.compile(r'\xA0[\xA0\x20]+|\x20[\xA0\x20]*\xA0[\xA0\x20]*')

_TS_TRUST_INHERITED = {'ts_ff', 'ts_fs'}


def clean(s: str) -> str:
    s = CLEAN_RE.sub('', s)
    s = _NBSP_RUN_RE.sub(' ', s)
    return s


def ts_explicit(sm: dict) -> dict:
    return {k: v for k, v in sm.items() if not k.endswith('_i') and v is not None}


_TS_NO_CROSS_PARA = {'ts_bd', 'ts_it'}


def get_ts(pos: int, text_anns: list, para_start: int | None = None) -> dict:
    s: dict = {}
    for si, ei, sm in text_anns:
        if si <= pos <= ei:
            for k, v in sm.items():
                if k.endswith('_i') or v is None or k in s:
                    continue
                if k in _TS_TRUST_INHERITED:
                    s[k] = v
                elif not sm.get(k + '_i', True):
                    if para_start is not None and k in _TS_NO_CROSS_PARA and si < para_start:
                        continue
                    s[k] = v
    return s


def style_run(run, ts: dict) -> None:
    run.font.name = ts.get('ts_ff', 'Arial')
    run.font.size = Pt(ts.get('ts_fs', 9))
    if 'ts_bd' in ts:
        run.font.bold = ts['ts_bd']
    if 'ts_it' in ts:
        run.font.italic = ts['ts_it']
    if 'ts_un' in ts:
        run.font.underline = ts['ts_un']
    if 'ts_st' in ts:
        run.font.strike = ts['ts_st']
    c = ts.get('ts_fgc2') or {}
    if isinstance(c, dict):
        h = (c.get('hclr_color') or '').lstrip('#')
        if h and h.lower() != '000000':
            try:
                rv, gv, bv = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
                if not (rv > 240 and gv > 240 and bv > 240):
                    run.font.color.rgb = RGBColor(rv, gv, bv)
            except Exception:
                pass
