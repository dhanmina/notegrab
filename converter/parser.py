import re
import json
from dataclasses import dataclass, field


@dataclass
class DocModel:
    full_text: str
    base: int
    para_styles: dict
    text_anns: list
    list_anns: dict
    list_defs: dict
    col_sectors: list


def parse_chunks(html: str) -> list:
    chunks = []
    for m in re.finditer(r'DOCS_modelChunk\s*=\s*(\{)', html):
        s = m.start(1)
        depth = 0
        for i, c in enumerate(html[s:], s):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            if depth == 0:
                try:
                    chunks.append(json.loads(html[s:i + 1]).get('chunk', []))
                except json.JSONDecodeError:
                    pass
                break
    return chunks


def build_model(chunks: list) -> DocModel:
    chunk_texts = sorted(
        [(it['ibi'], it['s']) for ch in chunks for it in ch if it.get('ty') == 'is'],
        key=lambda x: x[0],
    )
    if not chunk_texts:
        raise ValueError('No document text found in HTML. The document may be private.')

    full_text = ''.join(s for _, s in chunk_texts)
    base = chunk_texts[0][0]

    para_styles: dict = {}
    text_anns: list = []
    list_anns: dict = {}
    list_defs: dict = {}
    col_sectors: list = []

    for ch in chunks:
        for it in ch:
            ty = it.get('ty')
            st = it.get('st')
            si = it.get('si')
            ei = it.get('ei')
            sm = it.get('sm', {})
            if ty == 'as':
                if st == 'paragraph':
                    para_styles.setdefault(si, {}).update(sm)
                elif st == 'text':
                    text_anns.append((si, ei, sm))
                elif st == 'list':
                    list_anns[si] = sm
                elif st == 'column_sector':
                    col_sectors.append((si, sm))
            elif ty == 'ae' and it.get('et') == 'list':
                list_defs[it['id']] = it.get('epm', {})

    col_sectors.sort(key=lambda x: x[0])
    text_anns.sort(key=lambda x: x[1] - x[0])

    return DocModel(
        full_text=full_text,
        base=base,
        para_styles=para_styles,
        text_anns=text_anns,
        list_anns=list_anns,
        list_defs=list_defs,
        col_sectors=col_sectors,
    )


def extract_image_urls(html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for m in re.finditer(r'"(s-blob-v1-IMAGE-[^"]+)"\s*:\s*"([^"]+)"', html):
        key = m.group(1)
        val = m.group(2).replace('\\u003d', '=').replace('\\/', '/')
        result[key] = val
    return result
