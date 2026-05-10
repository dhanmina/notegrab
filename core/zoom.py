import json
import logging
import re
from urllib.parse import urljoin, urlparse, parse_qs

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def is_zoom_url(url: str) -> bool:
    return bool(re.match(r'https?://[^/]*\.?zoom\.us/rec/', url))


def _base_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/"


def _js_to_json(code: str) -> str:
    """Convert JS object literal to valid JSON."""
    code = re.sub(r'//[^\n]*', '', code)
    def _fix_quotes(m):
        inner = m.group(1).replace('\\"', '\\\\"').replace('"', '\\"')
        return f'"{inner}"'
    code = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", _fix_quotes, code)
    code = re.sub(r'(?m)(?<=[{,\n])\s*([a-zA-Z_$][\w$]*)\s*:', lambda m: f'"{m.group(1)}":', code)
    code = re.sub(r',\s*([}\]])', r'\1', code)
    return code


def _extract_balanced(html: str, start_marker: str) -> str | None:
    """Find start_marker in html, then extract the balanced {} block that follows."""
    idx = html.find(start_marker)
    if idx < 0:
        return None
    brace_start = html.find('{', idx)
    if brace_start < 0:
        return None

    depth = 0
    in_str = False
    str_char = None
    escaped = False
    i = brace_start

    while i < len(html):
        c = html[i]
        if escaped:
            escaped = False
        elif c == '\\' and in_str:
            escaped = True
        elif in_str:
            if c == str_char:
                in_str = False
        elif c in ('"', "'"):
            in_str = True
            str_char = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return html[brace_start:i + 1]
        i += 1
    return None


def _parse_page_data(html: str) -> dict | None:
    raw = _extract_balanced(html, 'window.__data__')
    if not raw:
        return None
    for transform in (lambda s: s, _js_to_json):
        try:
            return json.loads(transform(raw))
        except Exception:
            pass
    return None


def _find_form(html: str) -> dict | None:
    m = re.search(r'<form[^>]+id=["\']?password_form["\']?[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    inputs = {}
    for tag in re.finditer(r'<input[^>]+>', m.group(1), re.IGNORECASE):
        name = re.search(r'name=["\']?([^"\'>\s]+)', tag.group(0))
        val  = re.search(r'value=["\']?([^"\'>\s]*)', tag.group(0))
        if name:
            inputs[name.group(1)] = val.group(1) if val else ""
    return inputs


def _validate_passwd(session: requests.Session, base_url: str, meeting_id: str,
                     passwd: str, use_meeting: bool, action: str = "viewdetailpage") -> bool:
    endpoint = base_url + f"rec/validate{'_meet' if use_meeting else ''}_passwd"
    payload = {
        "id": meeting_id,
        "passwd": passwd,
        "action": action,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    try:
        resp = session.post(endpoint, data=payload, headers=headers)
        body = resp.json()
        logger.info("validate_passwd status=%d body=%s", resp.status_code, body)
        return bool(body.get("status"))
    except Exception as e:
        logger.warning("validate_passwd exception: %s", e)
        return False


def _get_play_info(session: requests.Session, base_url: str, file_id: str) -> dict:
    resp = session.get(
        f"{base_url}nws/recording/1.0/play/info/{file_id}",
        params={"continueMode": "true"},
    )
    return resp.json().get("result", {})


def _resolve_share_to_play(session: requests.Session, base_url: str,
                            share_url: str, password: str) -> str:
    """
    Given a share URL, authenticate and return the play URL.
    """
    resp = session.get(share_url)
    html = resp.text
    logger.info("share page status=%d url=%s", resp.status_code, resp.url)
    logger.debug("share page snippet: %s", html[:1000])

    # HTML password form on share page
    form = _find_form(html)
    logger.info("share page password form found: %s", form is not None)
    if form is not None:
        if not password:
            raise ValueError("This recording is password-protected")
        ok = _validate_passwd(session, base_url,
                         form.get("meetId") or form.get("fileId", ""),
                         password,
                         form.get("useWhichPasswd") == "meeting",
                         form.get("action", ""))
        logger.info("password form validation result: %s", ok)
        resp = session.get(share_url)
        html = resp.text
        logger.debug("share page after auth snippet: %s", html[:500])

    page_data = _parse_page_data(html)
    logger.info("page_data parsed: %s", page_data is not None)
    if not page_data:
        logger.error("could not parse window.__data__ from share page. url=%s snippet=%s", share_url, html[:2000])
        raise ValueError("Could not parse Zoom share page — page structure may have changed")

    meeting_id = page_data.get("meetingId")
    if not meeting_id:
        raise ValueError("meetingId not found on share page")

    return _resolve_meeting_to_play(session, base_url, meeting_id, password)


def _resolve_meeting_to_play(session: requests.Session, base_url: str,
                              meeting_id: str, password: str) -> str:
    """
    Given a meetingId, authenticate via API and return the play URL.
    """
    share_info_url = f"{base_url}nws/recording/1.0/play/share-info/{meeting_id}"
    resp = session.get(share_info_url)
    result = resp.json().get("result", {})
    logger.info("share-info status=%d componentName=%s", resp.status_code, result.get("componentName"))

    if result.get("componentName") == "need-password":
        if not password:
            raise ValueError("This recording is password-protected")
        ok = _validate_passwd(
            session, base_url,
            result.get("meetingId", meeting_id),
            password,
            result.get("useWhichPasswd") == "meeting",
            result.get("action", "viewdetailpage"),
        )
        if not ok:
            raise ValueError("Wrong password")
        resp2 = session.get(share_info_url)
        result = resp2.json().get("result", {})
        logger.info("share-info after auth: status=%d componentName=%s redirectUrl=%r",
                    resp2.status_code, result.get("componentName"), result.get("redirectUrl"))

    redirect_path = result.get("redirectUrl")
    logger.info("redirect_path=%r", redirect_path)
    if not redirect_path:
        raise ValueError("Authentication failed or recording unavailable")

    play_url = urljoin(base_url, redirect_path)
    if "continueMode" not in play_url:
        play_url += ("&" if "?" in play_url else "?") + "continueMode=true"
    return play_url


def get_zoom_video_info(url: str, password: str = "") -> tuple[str, str, dict, str]:
    """
    Returns (video_url, title, cookies, referer_base_url).
    Raises ValueError on auth failure or missing video.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    base = _base_url(url)
    session.headers["Referer"] = base

    parsed = urlparse(url)
    path = parsed.path

    # ── Determine URL type and get play URL ──
    if '/rec/share/' in path:
        # Zoom's SPA no longer embeds window.__data__ — try API with share token first
        share_token = path.rstrip('/').split('/')[-1]
        logger.info("share URL: trying API with token prefix %s…", share_token[:16])
        try:
            play_url = _resolve_meeting_to_play(session, base, share_token, password)
        except Exception as e:
            logger.info("share URL: API approach failed (%s), falling back to HTML scrape", e)
            play_url = _resolve_share_to_play(session, base, url, password)

    elif '/rec/component-page' in path:
        qs = parse_qs(parsed.query)
        meeting_id = (qs.get("meetingId") or [""])[0]
        origin = (qs.get("originRequestUrl") or [""])[0]
        if not meeting_id:
            raise ValueError("Could not extract meetingId from component-page URL")
        # Seed session cookies from the original share URL before API calls
        if origin:
            logger.info("component-page: seeding cookies from origin: %s", origin)
            try:
                session.get(origin, timeout=15)
            except Exception:
                pass
        play_url = _resolve_meeting_to_play(session, base, meeting_id, password)

        # Zoom returns a captcha redirect (component-page loop) when bot detection triggers.
        # After validate_passwd, the session has auth cookies — try play/info directly.
        if '/rec/component-page' in urlparse(play_url).path:
            logger.info("component-page: captcha redirect — trying direct play/info with meetingId")
            play_info = _get_play_info(session, base, meeting_id)
            for key in ("viewMp4WithshareUrl", "viewMp4Url", "shareMp4Url"):
                if play_info.get(key):
                    title = play_info.get("meet", {}).get("topic") or "Zoom Recording"
                    logger.info("Direct play/info succeeded: %s", title)
                    return play_info[key], title, dict(session.cookies), base
            raise ValueError("Zoom blocked the request — try again in a moment or use a different network")

    elif '/rec/play/' in path or '/rec/recording/play/' in path:
        play_url = url
        if "continueMode" not in play_url:
            play_url += ("&" if "?" in play_url else "?") + "continueMode=true"
        # Authenticate via originRequestUrl if present and password provided
        qs_play = parse_qs(parsed.query)
        origin = (qs_play.get("originRequestUrl") or [""])[0]
        if origin and password:
            share_token = urlparse(origin).path.rstrip('/').split('/')[-1]
            logger.info("play URL: authenticating via origin share token %s…", share_token[:16])
            try:
                _resolve_meeting_to_play(session, base, share_token, password)
            except Exception as e:
                logger.info("play URL: origin auth failed (%s), continuing unauthenticated", e)

    else:
        raise ValueError("Unrecognised Zoom recording URL")

    logger.info("Play URL: %s", play_url)

    # ── Try to get fileId from the play URL path directly ──
    file_id = None
    m = re.search(r'/rec/(?:recording/)?play/([^?&#/]+)', play_url)
    if m:
        file_id = m.group(1)
        logger.info("fileId from URL path: %s", file_id)

    # ── Fall back: load play page and parse window.__data__ ──
    if not file_id:
        session.headers["Referer"] = base
        resp = session.get(play_url)
        play_html = resp.text

        form = _find_form(play_html)
        if form is not None:
            if not password:
                raise ValueError("This recording is password-protected")
            _validate_passwd(session, base,
                             form.get("meetId") or form.get("fileId", ""),
                             password,
                             form.get("useWhichPasswd") == "meeting",
                             form.get("action", ""))
            resp = session.get(play_url)
            play_html = resp.text

        play_data = _parse_page_data(play_html)
        if play_data:
            file_id = play_data.get("fileId") or ""

        if not file_id:
            snippet = play_html[:3000]
            logger.error("Could not find fileId. play_url=%s page_snippet=%s", play_url, snippet)
            raise ValueError("Could not extract fileId from play page — see server log for details")

    # ── Fetch play info ──
    play_info = _get_play_info(session, base, file_id)
    title = play_info.get("meet", {}).get("topic") or "Zoom Recording"

    logger.info("play_info keys: %s", list(play_info.keys()))

    for key in ("viewMp4WithshareUrl", "viewMp4Url", "shareMp4Url"):
        if play_info.get(key):
            logger.info("Resolved video via %s: %s", key, title)
            return play_info[key], title, dict(session.cookies), base

    raise ValueError("No downloadable video URL found in play info")
