from copy import deepcopy
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.oxml.parser import parse_xml

from .styles import TAB_ALIGN_MAP

_PAGE_W_TWIPS = int(612.1 * 20)
_PAGE_H_TWIPS = int(936.1 * 20)
_MARGIN_TWIPS = int(36 * 20)
_HEADER_TWIPS = int(18 * 20)

_BORDER_STYLE_MAP = {0: 'none', 1: 'single', 4: 'thick', 8: 'double'}


def add_border(p, borders: dict) -> None:
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    for k, side in [('ps_bt', 'top'), ('ps_bb', 'bottom'), ('ps_bl', 'left'), ('ps_br', 'right')]:
        if k not in borders:
            continue
        b = borders[k]
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'), _BORDER_STYLE_MAP.get(int(b.get('brdr_s', 1)), 'single'))
        el.set(qn('w:sz'), str(int(b.get('brdr_w', 1.5) * 8)))
        el.set(qn('w:space'), '4')
        color = ((b.get('brdr_c2') or {}).get('hclr_color', '#000000') or '#000000').lstrip('#')
        el.set(qn('w:color'), color)
        pBdr.append(el)
    if len(pBdr):
        pPr.append(pBdr)


def add_tab_stops(p, ps_ts) -> None:
    stops = (ps_ts or {}).get('cv', {}).get('opValue', [])
    if not stops:
        return
    pPr = p._p.get_or_add_pPr()
    tabs = OxmlElement('w:tabs')
    for ts_item in stops:
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), TAB_ALIGN_MAP.get(ts_item.get('tbs_al', 0), 'left'))
        tab.set(qn('w:pos'), str(int(ts_item.get('tbs_of', 0) * 20)))
        tabs.append(tab)
    if len(tabs):
        pPr.append(tabs)


def extract_col_list(sec_sm: dict) -> list:
    raw = sec_sm.get('css_cols', {})
    if isinstance(raw, dict):
        return raw.get('cv', {}).get('opValue', [])
    return raw if isinstance(raw, list) else []


def get_cols_at(doc_pos: int, col_sectors: list) -> tuple[int, int]:
    n, space_twips = 1, 720
    for sec_si, sec_sm in col_sectors:
        if sec_si <= doc_pos:
            css = extract_col_list(sec_sm)
            n = len(css) if css else 1
            if n > 1 and css:
                space_twips = int((css[0].get('scol_pe') or 36) * 20)
        else:
            break
    return n, space_twips


def inject_col_section_break(p, cols: int, space_twips: int) -> None:
    pPr = p._p.get_or_add_pPr()
    sectPr = OxmlElement('w:sectPr')

    typ = OxmlElement('w:type')
    typ.set(qn('w:val'), 'continuous')
    sectPr.append(typ)

    wcols = OxmlElement('w:cols')
    wcols.set(qn('w:num'), str(cols))
    wcols.set(qn('w:space'), str(space_twips))
    sectPr.append(wcols)

    pgSz = OxmlElement('w:pgSz')
    pgSz.set(qn('w:w'), str(_PAGE_W_TWIPS))
    pgSz.set(qn('w:h'), str(_PAGE_H_TWIPS))
    sectPr.append(pgSz)

    pgMar = OxmlElement('w:pgMar')
    for attr, val in [('top', _MARGIN_TWIPS), ('right', _MARGIN_TWIPS),
                      ('bottom', _MARGIN_TWIPS), ('left', _MARGIN_TWIPS),
                      ('header', _HEADER_TWIPS), ('footer', _MARGIN_TWIPS)]:
        pgMar.set(qn(f'w:{attr}'), str(val))
    sectPr.append(pgMar)

    pPr.append(sectPr)


def inline_to_anchor(run, x_pt: float, y_pt: float, behind: bool = False,
                     v_relative_from: str = 'page') -> None:
    dr = run._r.find(qn('w:drawing'))
    if dr is None:
        return
    inl = dr.find(qn('wp:inline'))
    if inl is None:
        return
    extent = inl.find(qn('wp:extent'))
    cx, cy = extent.get('cx'), extent.get('cy')
    docPr = inl.find(qn('wp:docPr'))
    img_id, name = docPr.get('id'), docPr.get('name', 'Image')
    graphic = inl.find(qn('a:graphic'))
    PT = 12700
    bd = '1' if behind else '0'
    anc_xml = (
        f'<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        f' distT="0" distB="0" distL="0" distR="0" simplePos="0"'
        f' relativeHeight="251658240" behindDoc="{bd}" locked="0" layoutInCell="1" allowOverlap="1">'
        f'<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{int(x_pt * PT)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="{v_relative_from}"><wp:posOffset>{int(y_pt * PT)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:wrapNone/>'
        f'<wp:docPr id="{img_id}" name="{name}"/>'
        f'<wp:cNvGraphicFramePr/>'
        f'</wp:anchor>'
    )
    anc = parse_xml(anc_xml)
    anc.append(deepcopy(graphic))
    dr.remove(inl)
    dr.append(anc)
