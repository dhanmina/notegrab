import io
import logging
import os
import tempfile
from math import ceil

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .fetcher import extract_doc_id, download_html
from .parser import build_model, parse_chunks, extract_image_urls
from .styles import clean, get_ts
from .builder import _split_paragraphs, _fetch_images, _collect_image_elements
from .xml_helpers import get_cols_at

log = logging.getLogger(__name__)

_PT_MM = 25.4 / 72

_PW   = 612.1  * _PT_MM   # page width  mm
_PH   = 936.1  * _PT_MM   # page height mm
_MAR  = 36     * _PT_MM   # margin mm
_TW   = 540.1  * _PT_MM   # full text width mm
_CW   = 252.05 * _PT_MM   # single column width mm (2-col layout)
_CG   = 36     * _PT_MM   # column gap mm
_FH   = 7.0               # footer zone height mm


def _tmp(data: bytes, suffix: str = '.png') -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


class _PDF(FPDF):
    def __init__(self, logo_path, logo_w, logo_h, bg_path, bg_w, bg_h):
        super().__init__(unit='mm', format=(_PW, _PH))
        self.set_margins(_MAR, _MAR, _MAR)
        self.set_auto_page_break(False)

        self._logo_path = logo_path
        self._logo_w    = logo_w
        self._logo_h    = logo_h
        self._bg_path   = bg_path
        self._bg_w      = bg_w
        self._bg_h      = bg_h

        # column state
        self._n_cols  = 1
        self._col     = 0
        self._col_y   = [_MAR, _MAR]
        self._col_x   = [_MAR, _MAR + _CW + _CG]

    # ── low-level page painters ───────────────────────────────────────────────

    def _paint_bg(self):
        if self._bg_path:
            x = (_PW - self._bg_w) / 2
            self.image(self._bg_path, x=x, y=_MAR, w=self._bg_w, h=self._bg_h)

    def _paint_logo(self):
        if self._logo_path:
            x = (_PW - self._logo_w) / 2
            self.image(self._logo_path, x=x, y=_MAR, w=self._logo_w, h=self._logo_h)

    def _paint_footer(self):
        fy = _PH - _MAR - _FH + 1
        self.set_draw_color(170, 170, 170)
        self.set_line_width(0.2)
        self.line(_MAR, fy - 1, _PW - _MAR, fy - 1)

        p = str(self.page)
        self.set_font('Helvetica', 'B', 9)
        pw  = self.get_string_width(p)
        self.set_font('Helvetica', '', 9)
        piw = self.get_string_width(' | ')
        pgw = self.get_string_width('Page')
        x = _PW - _MAR - pw - piw - pgw

        self.set_xy(x, fy)
        self.set_text_color(0, 0, 0)
        self.set_font('Helvetica', 'B', 9)
        self.cell(pw, _FH - 1, p)
        self.set_font('Helvetica', '', 9)
        self.cell(piw, _FH - 1, ' | ')
        self.set_text_color(128, 128, 128)
        self.cell(pgw, _FH - 1, 'Page')

    # ── page lifecycle ────────────────────────────────────────────────────────

    def start(self, n_cols: int = 1):
        self._n_cols = n_cols
        self._new_page(first=True)

    def _new_page(self, first: bool = False):
        if self.page > 0:
            self._paint_footer()
        self.add_page()
        self._paint_bg()
        if first and self._logo_path:
            self._paint_logo()

        top = _MAR
        if first and self._logo_path:
            top = _MAR + self._logo_h + 2
        self._col   = 0
        self._col_y = [top, top]

    def finish(self):
        self._paint_footer()

    # ── column helpers ────────────────────────────────────────────────────────

    def _cx(self) -> float:
        return _MAR if self._n_cols == 1 else self._col_x[self._col]

    def _cy(self) -> float:
        return self._col_y[self._col if self._n_cols > 1 else 0]

    def _cw(self) -> float:
        return _TW if self._n_cols == 1 else _CW

    def _col_max_y(self) -> float:
        return _PH - _MAR - _FH - 1

    def _ensure(self, h: float):
        """Make sure h mm fits; advance column or add page as needed."""
        if self._cy() + h <= self._col_max_y():
            return
        if self._n_cols > 1 and self._col == 0:
            self._col = 1
            if self._cy() + h <= self._col_max_y():
                return
        self._new_page()

    def _set_n_cols(self, n: int):
        if n != self._n_cols:
            self._n_cols = n
            self._col    = 0

    # ── height estimation ─────────────────────────────────────────────────────

    def _est_h(self, text: str, font_size: float, style: str, n_cols: int) -> float:
        self.set_font('Helvetica', style, font_size)
        w = _TW if n_cols == 1 else _CW
        lh = font_size * _PT_MM * 1.4
        segments = (text or '').split('\n')
        total = 0.0
        for seg in segments:
            if not seg.strip():
                total += lh * 0.5
                continue
            seg = seg.replace('\t', '   ')
            sw = self.get_string_width(seg)
            total += max(1, ceil(sw / w)) * lh
        return total

    # ── paragraph renderer ────────────────────────────────────────────────────

    def write_para(self, text: str, ps: dict, ts: dict, n_cols: int):
        self._set_n_cols(n_cols)

        font_size = float(ts.get('ts_fs', 9))
        bold      = ts.get('ts_bd', False)
        italic    = ts.get('ts_it', False)
        style     = ('B' if bold else '') + ('I' if italic else '')

        col_obj = ts.get('ts_fgc2') or {}
        h_hex   = (col_obj.get('hclr_color') or '000000').lstrip('#')
        try:
            r, g, b = int(h_hex[:2], 16), int(h_hex[2:4], 16), int(h_hex[4:], 16)
        except (ValueError, IndexError):
            r, g, b = 0, 0, 0

        al_map = {0: 'L', 1: 'C', 2: 'R', 3: 'J'}
        align  = al_map.get(ps.get('ps_al'), 'L')
        il_mm  = (ps.get('ps_il') or 0) * _PT_MM
        lh     = max(font_size * _PT_MM * 1.4, 4.0)

        if not text.strip():
            sb_mm = (ps.get('ps_sb') or 0) * _PT_MM
            self._col_y[self._col if self._n_cols > 1 else 0] += max(lh * 0.4, sb_mm)
            return

        est = self._est_h(text, font_size, style, n_cols)
        self._ensure(est)

        self.set_font('Helvetica', style, font_size)
        self.set_text_color(r, g, b)

        x = self._cx()
        w = self._cw()

        for seg in text.split('\n'):
            seg = seg.replace('\t', '   ')
            if not seg:
                self._col_y[self._col if self._n_cols > 1 else 0] += lh * 0.5
                continue
            self.set_xy(x + il_mm, self._cy())
            before_y = self.get_y()
            self.multi_cell(
                w - il_mm, lh, seg,
                align=align,
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            after_y = self.get_y()
            self._col_y[self._col if self._n_cols > 1 else 0] += (after_y - before_y)

        sa_mm = (ps.get('ps_sa') or 0) * _PT_MM
        if sa_mm > 0:
            self._col_y[self._col if self._n_cols > 1 else 0] += sa_mm


# ── public entry point ────────────────────────────────────────────────────────

def build_pdf(url_or_id: str) -> bytes:
    log.info('PDF build started for: %s', url_or_id)

    doc_id = extract_doc_id(url_or_id)
    if not doc_id:
        raise ValueError('Could not extract document ID.')

    html   = download_html(doc_id)
    chunks = parse_chunks(html)
    if not chunks:
        raise ValueError('No document model found.')

    model      = build_model(chunks)
    images     = _fetch_images(extract_image_urls(html))
    img_elems  = _collect_image_elements(chunks, images)
    paragraphs = _split_paragraphs(model.full_text, model.base)

    logo_imgs = [m for m in img_elems if m['y_pt'] < 0]
    bg_imgs   = [m for m in img_elems if m['y_pt'] >= 0]

    tmp_files = []
    try:
        logo_path = bg_path = None
        logo_w = logo_h = bg_w = bg_h = 0.0

        if logo_imgs:
            m         = logo_imgs[0]
            logo_path = _tmp(images[m['cid']])
            tmp_files.append(logo_path)
            logo_w = m['w_pt'] * _PT_MM
            logo_h = m['h_pt'] * _PT_MM

        if bg_imgs:
            m       = bg_imgs[0]
            bg_path = _tmp(images[m['cid']])
            tmp_files.append(bg_path)
            bg_w = m['w_pt'] * _PT_MM
            bg_h = m['h_pt'] * _PT_MM

        # Determine initial column count
        first_cols = 1
        if model.col_sectors:
            first_cols, _ = get_cols_at(model.col_sectors[0][0], model.col_sectors)

        pdf = _PDF(logo_path, logo_w, logo_h, bg_path, bg_w, bg_h)
        pdf.start(n_cols=first_cols)

        for para_text, pep, str_start in paragraphs:
            ps = model.para_styles.get(pep, {}) if pep else {}

            # Dominant style from first non-whitespace character
            ts: dict = {}
            for i, ch in enumerate(para_text):
                if ch.strip():
                    ts = get_ts(model.base + str_start + i, model.text_anns)
                    break

            text = clean(para_text)

            n_cols = 1
            if pep and model.col_sectors:
                n_cols, _ = get_cols_at(pep, model.col_sectors)

            pdf.write_para(text, ps, ts, n_cols)

        pdf.finish()

        buf = io.BytesIO()
        pdf.output(buf)
        log.info('PDF build done  size=%d bytes', buf.tell())
        return buf.getvalue()

    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
