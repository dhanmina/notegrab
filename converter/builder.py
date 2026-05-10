import io
import logging

from docx import Document
from docx.shared import Pt, Emu, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from .fetcher import extract_doc_id, download_html, fetch_image
from .parser import build_model, parse_chunks, extract_image_urls, DocModel
from .styles import ALIGN_MAP, clean, get_ts, style_run
from .xml_helpers import (
    add_border, add_tab_stops, extract_col_list,
    get_cols_at, inject_col_section_break, inline_to_anchor,
)
from .lists import make_label

log = logging.getLogger(__name__)

_PAGE_W_PT = 612.1


def _init_document() -> Document:
    doc = Document()
    for sec in doc.sections:
        sec.page_width = Emu(int(_PAGE_W_PT * 12700))
        sec.page_height = Emu(int(936.1 * 12700))
        sec.top_margin = Pt(36)
        sec.bottom_margin = Pt(36)
        sec.left_margin = Pt(36)
        sec.right_margin = Pt(36)
        sec.header_distance = Pt(18)
    for ep in list(doc.paragraphs):
        ep._element.getparent().remove(ep._element)
    return doc


def _fetch_images(img_urls: dict[str, str]) -> dict[str, bytes]:
    images: dict[str, bytes] = {}
    for cid, url in img_urls.items():
        data = fetch_image(url)
        if data:
            images[cid] = data
    return images


def _collect_image_elements(chunks: list, images: dict[str, bytes]) -> list[dict]:
    elements = []
    for ch in chunks:
        for it in ch:
            if it.get('ty') != 'ae':
                continue
            epm = it.get('epm', {})
            eo = epm.get('ee_eo', {})
            cid = eo.get('i_cid')
            if not cid or cid not in images:
                continue
            pos = epm.get('ae_p', {})
            elements.append({
                'cid': cid,
                'w_pt': eo.get('i_wth', 100),
                'h_pt': eo.get('i_ht', 100),
                'x_pt': pos.get('p_hp', {}).get('hp_lo', 0),
                'y_pt': pos.get('p_vp', {}).get('vp_to', 0),
                'behind': pos.get('p_bd', False),
            })
    return elements


def _split_paragraphs(full_text: str, base: int) -> list[tuple[str, int | None, int]]:
    paragraphs: list[tuple[str, int | None, int]] = []
    seg = 0
    for i, ch in enumerate(full_text):
        if ch == '\n':
            paragraphs.append((full_text[seg:i], i + base, seg))
            seg = i + 1
    if seg < len(full_text):
        paragraphs.append((full_text[seg:], None, seg))

    # Drop leading empty paragraphs that exist only as logo spacers in the original.
    # After cleaning, these contain nothing visible (only private-use chars like ).
    while paragraphs and not clean(paragraphs[0][0]).strip():
        paragraphs.pop(0)

    # Drop trailing paragraphs that are empty or are the "| Page" page-number artifact
    # (Google Docs embeds a private-use glyph + "| Page" label in the body as a field).
    while paragraphs and not clean(paragraphs[-1][0]).strip().lstrip('| ').lower().replace('page', '').strip():
        paragraphs.pop()

    return paragraphs


def _apply_paragraph_format(p, ps: dict, la) -> None:
    al = ps.get('ps_al')
    if al is not None and not ps.get('ps_al_i', True):
        p.alignment = ALIGN_MAP.get(al, WD_ALIGN_PARAGRAPH.LEFT)

    pf = p.paragraph_format

    # ps_ifl is an absolute position; first_line_indent in OOXML is relative to left_indent
    il = ps.get('ps_il')
    if il is not None and not ps.get('ps_il_i', True):
        pf.left_indent = Pt(il)
    ifl = ps.get('ps_ifl')
    if ifl is not None and not ps.get('ps_ifl_i', True):
        pf.first_line_indent = Pt(ifl - (il or 0))
    elif la is not None and il is not None and not ps.get('ps_il_i', True):
        pf.first_line_indent = Pt(-18)

    # Default to 0 to suppress Word's Normal-style spacing
    sb = ps.get('ps_sb')
    pf.space_before = Pt(sb) if sb is not None and not ps.get('ps_sb_i', True) else Pt(0)
    sa = ps.get('ps_sa')
    pf.space_after = Pt(sa) if sa is not None and not ps.get('ps_sa_i', True) else Pt(0)

    ls = ps.get('ps_ls')
    if ls is not None and not ps.get('ps_ls_i', True):
        pf.line_spacing = ls
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE

    brd = {k: ps[k] for k in ('ps_bt', 'ps_bb', 'ps_bl', 'ps_br') if k in ps}
    if brd:
        add_border(p, brd)

    ps_ts = ps.get('ps_ts')
    if ps_ts:
        add_tab_stops(p, ps_ts)


def _add_text_runs(p, para_text: str, str_start: int, base: int, text_anns: list) -> None:
    # Split on \x0b (soft return) BEFORE cleaning so positions stay aligned
    sub_off = 0
    for seg_i, segment in enumerate(para_text.split('\x0b')):
        if seg_i > 0:
            r = p.add_run()
            r.add_break()
            sub_off += 1  # consume the \x0b
        if not segment:
            sub_off += len(segment)
            continue
        i = 0
        while i < len(segment):
            cp = base + str_start + sub_off + i
            ts = get_ts(cp, text_anns)
            j = i + 1
            while j < len(segment) and get_ts(base + str_start + sub_off + j, text_anns) == ts:
                j += 1
            run_text = clean(segment[i:j])
            if run_text:
                r = p.add_run(run_text)
                style_run(r, ts)
            i = j
        sub_off += len(segment)


def _build_paragraphs(doc: Document, paragraphs: list, model: DocModel) -> None:
    list_ctrs: dict = {}
    for idx, (para_text, pep, str_start) in enumerate(paragraphs):
        ps = model.para_styles.get(pep, {}) if pep else {}
        la = model.list_anns.get(pep)
        p = doc.add_paragraph()

        _apply_paragraph_format(p, ps, la)

        if la and ps.get('ps_sm') is not None and not ps.get('ps_sm_i', True):
            lbl, lts = make_label(la.get('ls_id', ''), ps.get('ps_sm', 1), la, model.list_defs, list_ctrs)
            lr = p.add_run(clean(lbl))
            style_run(lr, lts)

        _add_text_runs(p, para_text, str_start, model.base, model.text_anns)

        if pep is not None and model.col_sectors:
            cur_cols, cur_space = get_cols_at(pep, model.col_sectors)
            next_pep = paragraphs[idx + 1][1] if idx + 1 < len(paragraphs) else None
            if next_pep is not None:
                next_cols, _ = get_cols_at(next_pep, model.col_sectors)
                if next_cols != cur_cols:
                    inject_col_section_break(p, cur_cols, cur_space)


def _apply_final_columns(doc: Document, col_sectors: list) -> None:
    if not col_sectors:
        return
    css = extract_col_list(col_sectors[-1][1])
    if len(css) <= 1:
        return
    space_tw = int((css[0].get('scol_pe') or 36) * 20)
    body = doc.element.body
    sectPr = body.find(qn('w:sectPr'))
    if sectPr is not None:
        for old in sectPr.findall(qn('w:cols')):
            sectPr.remove(old)
        wcols = OxmlElement('w:cols')
        wcols.set(qn('w:num'), str(len(css)))
        wcols.set(qn('w:space'), str(space_tw))
        sectPr.append(wcols)
        # Without an explicit type, OOXML defaults the body sectPr to "nextPage",
        # which would push the multi-column section to a new page. Mark it
        # continuous so it flows directly after the preceding single-column section.
        for old in sectPr.findall(qn('w:type')):
            sectPr.remove(old)
        wtype = OxmlElement('w:type')
        wtype.set(qn('w:val'), 'continuous')
        sectPr.insert(0, wtype)
        log.debug('Applied %d-column layout to body sectPr (continuous)', len(css))


def _build_headers(doc: Document, img_elements: list, images: dict[str, bytes]) -> None:
    logo_imgs = [m for m in img_elements if m['y_pt'] < 0]
    bg_imgs = [m for m in img_elements if m['y_pt'] >= 0]
    sec0 = doc.sections[0]

    if logo_imgs:
        sec0.different_first_page_header_footer = True
        fph = sec0.first_page_header
        fph.is_linked_to_previous = False
        fhp = fph.paragraphs[0]
        fhp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fhp.paragraph_format.space_before = Pt(0)
        fhp.paragraph_format.space_after = Pt(0)
        for m in logo_imgs:
            run = fhp.add_run()
            run.add_picture(io.BytesIO(images[m['cid']]), width=Pt(m['w_pt']), height=Pt(m['h_pt']))
        # Also add background to first-page header so page 1 gets it too
        for m in bg_imgs:
            run = fhp.add_run()
            run.add_picture(io.BytesIO(images[m['cid']]), width=Pt(m['w_pt']), height=Pt(m['h_pt']))
            x = (_PAGE_W_PT - m['w_pt']) / 2 if m['w_pt'] < _PAGE_W_PT else 0
            inline_to_anchor(run, x_pt=x, y_pt=m['y_pt'], behind=m['behind'], v_relative_from='page')

    # Default header (page 2+): background only
    for sec in doc.sections:
        hdr = sec.header
        hdr.is_linked_to_previous = False
        hp = hdr.paragraphs[0]
        for m in bg_imgs:
            run = hp.add_run()
            run.add_picture(io.BytesIO(images[m['cid']]), width=Pt(m['w_pt']), height=Pt(m['h_pt']))
            x = (_PAGE_W_PT - m['w_pt']) / 2 if m['w_pt'] < _PAGE_W_PT else 0
            inline_to_anchor(run, x_pt=x, y_pt=m['y_pt'], behind=m['behind'], v_relative_from='page')



def _build_footer(doc: Document) -> None:
    sec = doc.sections[0]
    footers = [sec.footer]
    if sec.different_first_page_header_footer:
        footers.append(sec.first_page_footer)

    for ftr in footers:
        ftr.is_linked_to_previous = False
        _populate_footer_paragraph(ftr.paragraphs[0])


def _populate_footer_paragraph(fp) -> None:
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    fp.paragraph_format.space_before = Pt(4)
    fp.paragraph_format.space_after = Pt(0)

    pPr = fp._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    top = OxmlElement('w:top')
    top.set(qn('w:val'), 'single')
    top.set(qn('w:sz'), '4')
    top.set(qn('w:space'), '1')
    top.set(qn('w:color'), 'AAAAAA')
    pBdr.append(top)
    pPr.append(pBdr)

    def _make_run(color='000000'):
        r = OxmlElement('w:r')
        rpr = OxmlElement('w:rPr')
        fonts = OxmlElement('w:rFonts')
        fonts.set(qn('w:ascii'), 'Arial')
        fonts.set(qn('w:hAnsi'), 'Arial')
        rpr.append(fonts)
        if color:
            c = OxmlElement('w:color')
            c.set(qn('w:val'), color)
            rpr.append(c)
        sz = OxmlElement('w:sz')
        sz.set(qn('w:val'), '20')
        rpr.append(sz)
        r.append(rpr)
        return r

    # begin
    r_begin = _make_run()
    fc_begin = OxmlElement('w:fldChar')
    fc_begin.set(qn('w:fldCharType'), 'begin')
    r_begin.append(fc_begin)
    fp._p.append(r_begin)

    # instr
    r_instr = _make_run()
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = ' PAGE '
    r_instr.append(instr)
    fp._p.append(r_instr)

    # separate + display value (Word replaces "1" with the real page number)
    r_sep = _make_run()
    fc_sep = OxmlElement('w:fldChar')
    fc_sep.set(qn('w:fldCharType'), 'separate')
    r_sep.append(fc_sep)
    fp._p.append(r_sep)

    r_val = _make_run()
    t = OxmlElement('w:t')
    t.text = '1'
    r_val.append(t)
    fp._p.append(r_val)

    # end
    r_end = _make_run()
    fc_end = OxmlElement('w:fldChar')
    fc_end.set(qn('w:fldCharType'), 'end')
    r_end.append(fc_end)
    fp._p.append(r_end)

    fr_pipe = fp.add_run(' | ')
    fr_pipe.font.name = 'Arial'
    fr_pipe.font.size = Pt(10)
    fr_pipe.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    fr_label = fp.add_run('Page')
    fr_label.font.name = 'Arial'
    fr_label.font.size = Pt(10)
    fr_label.font.color.rgb = RGBColor(0x80, 0x80, 0x80)


def convert(url_or_id: str) -> bytes:
    log.info('Starting conversion for: %s', url_or_id)

    doc_id = extract_doc_id(url_or_id)
    if not doc_id:
        raise ValueError('Could not extract a document ID from the provided URL.')
    log.info('Resolved doc ID: %s', doc_id)

    html = download_html(doc_id)
    log.info('Downloaded HTML (%d bytes)', len(html))

    chunks = parse_chunks(html)
    if not chunks:
        raise ValueError('No document model found. The document may be private or inaccessible.')
    log.info('Parsed %d chunks', len(chunks))

    model = build_model(chunks)
    log.info('Built model: %d chars, %d para styles, %d text anns, %d col sectors',
             len(model.full_text), len(model.para_styles), len(model.text_anns), len(model.col_sectors))

    img_urls = extract_image_urls(html)
    log.info('Found %d image URLs', len(img_urls))
    images = _fetch_images(img_urls)
    log.info('Fetched %d images', len(images))

    img_elements = _collect_image_elements(chunks, images)
    logo_imgs = [m for m in img_elements if m['y_pt'] < 0]
    bg_imgs = [m for m in img_elements if m['y_pt'] >= 0]
    log.info('Image elements: %d logo, %d background', len(logo_imgs), len(bg_imgs))
    for m in logo_imgs:
        log.debug('Logo image: w=%.1fpt h=%.1fpt y=%.1fpt', m['w_pt'], m['h_pt'], m['y_pt'])
    for m in bg_imgs:
        log.debug('BG image: w=%.1fpt h=%.1fpt y=%.1fpt behind=%s', m['w_pt'], m['h_pt'], m['y_pt'], m['behind'])

    doc = _init_document()
    paragraphs = _split_paragraphs(model.full_text, model.base)
    log.info('Split into %d paragraphs (after stripping artifacts)', len(paragraphs))

    _build_paragraphs(doc, paragraphs, model)
    log.info('Built %d document paragraphs', len(doc.paragraphs))

    _apply_final_columns(doc, model.col_sectors)

    if img_elements:
        _build_headers(doc, img_elements, images)
        log.info('Built headers (first_page=%s)', bool(logo_imgs))

    _build_footer(doc)
    log.info('Built footer')

    buf = io.BytesIO()
    doc.save(buf)
    size = buf.tell()
    log.info('Saved document (%d bytes)', size)
    buf.seek(0)
    return buf.read()
