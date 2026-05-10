import re
import logging
import requests

log = logging.getLogger(__name__)

_DOC_ID_PATTERNS = [
    r'/document/d/([a-zA-Z0-9_-]+)',
    r'id=([a-zA-Z0-9_-]+)',
    r'^([a-zA-Z0-9_-]{25,})$',
]


def extract_doc_id(url: str) -> str | None:
    url = url.strip()
    for pat in _DOC_ID_PATTERNS:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def download_html(doc_id: str) -> str:
    url = f'https://docs.google.com/document/d/{doc_id}'
    log.info('Downloading HTML from %s', url)
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    log.info('Downloaded %d bytes (status %d)', len(r.text), r.status_code)
    return r.text


def fetch_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.headers.get('content-type', '').startswith('image/'):
            log.debug('Fetched image %d bytes from %s', len(r.content), url[:60])
            return r.content
        log.warning('Unexpected image response: status=%d content-type=%s url=%s',
                    r.status_code, r.headers.get('content-type'), url[:60])
    except Exception as e:
        log.error('Failed to fetch image %s: %s', url[:60], e)
    return None
