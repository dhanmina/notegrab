import re
from .styles import ts_explicit


def make_label(ls_id: str, ps_sm: int, la: dict, list_defs: dict, list_ctrs: dict) -> tuple[str, dict]:
    lv = f"nl_{max(0, ps_sm - 1)}"
    key = (ls_id, lv)
    nb = list_defs.get(ls_id, {}).get('le_nb', {}).get(lv, {})
    b_gt = nb.get('b_gt', 10)
    b_gf = nb.get('b_gf', '%0.')
    b_sn = nb.get('b_sn', 1)

    if b_gt == 0:
        return (nb.get('b_gs') or '•') + '\t', ts_explicit(la.get('ls_ts', {}))

    if key not in list_ctrs:
        list_ctrs[key] = 0 if b_gt in (12, 13) else b_sn
    else:
        list_ctrs[key] += 1

    n = list_ctrs[key]
    if b_gt == 12:
        lbl = re.sub(r'%\d', chr(ord('A') + n), b_gf)
    elif b_gt == 13:
        lbl = re.sub(r'%\d', chr(ord('a') + n), b_gf)
    else:
        lbl = re.sub(r'%\d', str(n), b_gf)
    return lbl + '\t', ts_explicit(la.get('ls_ts', {}))
