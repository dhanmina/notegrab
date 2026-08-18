import json
import logging
import re
import threading
import time
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
    code = re.sub(r'//[^\n]*', '', code)
    def _fix_quotes(m):
        inner = m.group(1).replace('\\"', '\\\\"').replace('"', '\\"')
        return f'"{inner}"'
    code = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", _fix_quotes, code)
    code = re.sub(r'(?m)(?<=[{,\n])\s*([a-zA-Z_$][\w$]*)\s*:', lambda m: f'"{m.group(1)}":', code)
    code = re.sub(r',\s*([}\]])', r'\1', code)
    return code


def _extract_balanced(html: str, start_marker: str) -> str | None:
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


def _validate_passwd_nws(session: requests.Session, base_url: str, meeting_id: str,
                         passwd: str, action: str = "viewdetailpage") -> bool:
    endpoint = f"{base_url}nws/recording/1.0/play/validate-passwd"
    payload = {"id": meeting_id, "passwd": passwd, "action": action}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base_url,
    }
    try:
        resp = session.post(endpoint, data=payload, headers=headers)
        body = resp.json()
        logger.info("validate_passwd_nws status=%d body=%s", resp.status_code, body)
        return bool(body.get("status"))
    except Exception as e:
        logger.warning("validate_passwd_nws exception: %s", e)
        return False


def _validate_passwd(session: requests.Session, base_url: str, meeting_id: str,
                     passwd: str, use_meeting: bool, action: str = "viewdetailpage") -> bool | None:
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
        if not body.get("status") and "deprecated" in body.get("errorMessage", "").lower():
            logger.warning("validate_passwd API is deprecated — will try share-page fallback")
            return None
        return bool(body.get("status"))
    except Exception as e:
        logger.warning("validate_passwd exception: %s", e)
        return False


def _auth_via_share_page(session: requests.Session, base_url: str,
                          meeting_id: str, password: str) -> dict | None:
    import base64
    share_url = f"{base_url}rec/share/{meeting_id}"
    for pwd in (password, base64.b64encode(password.encode()).decode()):
        try:
            resp = session.get(share_url, params={"pwd": pwd}, timeout=15)
            logger.info("share-page pwd auth: status=%d final_url=%s", resp.status_code, resp.url)
            html = resp.text
            page_data = _parse_page_data(html)
            if page_data:
                logger.info("share-page pwd auth: parsed window.__data__ keys=%s", list(page_data.keys())[:8])
                return page_data
            if "password_form" not in html and "need-password" not in html.lower():
                logger.info("share-page pwd auth: page loaded without password gate")
                return {}
        except Exception as e:
            logger.warning("share-page pwd auth attempt failed: %s", e)
    return None


def _get_play_info(session: requests.Session, base_url: str, file_id: str,
                   passwd: str = "", referer: str = "") -> dict:
    headers = {}
    if referer:
        headers["Referer"] = referer
    params: dict = {"continueMode": "true"}
    if passwd:
        params["passwd"] = passwd
    resp = session.get(
        f"{base_url}nws/recording/1.0/play/info/{file_id}",
        params=params,
        headers=headers,
    )
    return resp.json().get("result") or {}


def _is_play_info_auth_challenge(info: dict) -> bool:
    return bool(info.get("componentName") or info.get("needRedirect"))


def _resolve_share_to_play(session: requests.Session, base_url: str,
                            share_url: str, password: str) -> str:
    resp = session.get(share_url)
    html = resp.text
    logger.info("share page status=%d url=%s", resp.status_code, resp.url)
    logger.debug("share page snippet: %s", html[:1000])

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
    share_info_url = f"{base_url}nws/recording/1.0/play/share-info/{meeting_id}"
    resp = session.get(share_info_url)
    result = resp.json().get("result", {})
    logger.info("share-info status=%d componentName=%s", resp.status_code, result.get("componentName"))

    if result.get("componentName") == "play-forbidden":
        raise ValueError("This Zoom recording is not available (expired or deleted)")

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
        if ok is None:
            challenge_id = result.get("meetingId", meeting_id)
            ok_nws = _validate_passwd_nws(session, base_url, challenge_id, password,
                                          result.get("action", "viewdetailpage"))
            if not ok_nws:
                page_data = _auth_via_share_page(session, base_url, meeting_id, password)
                if page_data is None:
                    raise ValueError(
                        "This recording requires a Zoom login to access. "
                        "Please provide your Zoom session cookie (_zm_ssid) in the advanced field."
                    )
                session._share_page_data = page_data
        elif not ok:
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


def get_zoom_video_info(url: str, password: str = "",
                        zoom_session: str = "") -> tuple[str, str, dict, str]:
    session = requests.Session()
    session.headers.update(_HEADERS)
    base = _base_url(url)
    session.headers["Referer"] = base
    if zoom_session:
        session.cookies.set("_zm_ssid", zoom_session, domain="zoom.us")

    parsed = urlparse(url)
    path = parsed.path

    if '/rec/share/' in path:
        share_token = path.rstrip('/').split('/')[-1]
        logger.info("share URL: trying API with token prefix %s…", share_token[:16])
        try:
            play_url = _resolve_meeting_to_play(session, base, share_token, password)
        except Exception as e:
            logger.info("share URL: API approach failed (%s), falling back to HTML scrape", e)
            play_url = _resolve_share_to_play(session, base, url, password)

    elif '/rec/component-page' in path:
        qs = parse_qs(parsed.query)
        component_name = (qs.get("componentName") or [""])[0]
        if component_name == "play-forbidden":
            message = (qs.get("message") or [""])[0]
            raise ValueError(message or "This Zoom recording is not available")
        meeting_id = (qs.get("meetingId") or [""])[0]
        origin = (qs.get("originRequestUrl") or [""])[0]
        if not meeting_id:
            raise ValueError("Could not extract meetingId from component-page URL")
        if origin:
            logger.info("component-page: seeding cookies from origin: %s", origin)
            try:
                session.get(origin, timeout=15)
            except Exception:
                pass
        play_url = _resolve_meeting_to_play(session, base, meeting_id, password)

        if '/rec/component-page' in urlparse(play_url).path:
            logger.info("component-page: captcha redirect — trying direct play/info with meetingId")
            play_info = _get_play_info(session, base, meeting_id, passwd=password)
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

    file_id = None
    m = re.search(r'/rec/(?:recording/)?play/([^?&#/]+)', play_url)
    if m:
        file_id = m.group(1)
        logger.info("fileId from URL path: %s", file_id)

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

    play_info = _get_play_info(session, base, file_id, passwd=password, referer=play_url)
    logger.info("play_info keys: %s", list(play_info.keys()))

    if _is_play_info_auth_challenge(play_info) and file_id:
        logger.info("play_info auth challenge — loading play page to seed cookies then retrying")
        try:
            session.headers["Referer"] = base
            resp = session.get(play_url, timeout=20)
            play_html = resp.text
            form = _find_form(play_html)
            if form is not None and password:
                ok = _validate_passwd(session, base,
                                      form.get("meetId") or form.get("fileId", ""),
                                      password,
                                      form.get("useWhichPasswd") == "meeting",
                                      form.get("action", ""))
                if ok is None:
                    session.get(play_url + ("&" if "?" in play_url else "?") + f"pwd={password}", timeout=15)
                resp = session.get(play_url, timeout=20)
                play_html = resp.text
            play_data = _parse_page_data(play_html)
            if play_data:
                for key in ("viewMp4WithshareUrl", "viewMp4Url", "shareMp4Url"):
                    if play_data.get(key):
                        title = play_data.get("meet", {}).get("topic") or "Zoom Recording"
                        logger.info("Resolved video from play page __data__ via %s", key)
                        return play_data[key], title, dict(session.cookies), base
                if play_data.get("fileId"):
                    file_id = play_data["fileId"]
        except Exception as e:
            logger.warning("play page seed attempt failed: %s", e)
        play_info = _get_play_info(session, base, file_id, passwd=password, referer=play_url)
        logger.info("play_info retry keys: %s", list(play_info.keys()))

    title = play_info.get("meet", {}).get("topic") or "Zoom Recording"

    for key in ("viewMp4WithshareUrl", "viewMp4Url", "shareMp4Url"):
        if play_info.get(key):
            logger.info("Resolved video via %s: %s", key, title)
            return play_info[key], title, dict(session.cookies), base

    logger.info("HTTP approach failed — trying Playwright fallback")
    return _get_zoom_info_playwright(url, password)


def _get_zoom_info_playwright(url: str, password: str) -> tuple[str, str, dict, str]:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise ValueError(
            "This recording requires browser-based authentication. "
            "Install playwright: pip install playwright && playwright install chromium"
        )

    base = _base_url(url)

    parsed = urlparse(url)
    if "/rec/share/" in parsed.path:
        nav_url = url
    else:
        qs = parse_qs(parsed.query)
        origin = (qs.get("originRequestUrl") or [""])[0]
        nav_url = origin if origin else url

    result_box: list = []
    error_box: list[str] = []

    play_url_for_nav = url if "/rec/play/" in parsed.path else None

    def run():
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=_HEADERS["User-Agent"],
                    extra_http_headers={"Accept-Language": _HEADERS["Accept-Language"]},
                )
                page = context.new_page()

                logger.info("Playwright: navigating to %s", nav_url[:80])
                page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)

                if password:
                    try:
                        page.wait_for_selector('input[type="password"]', timeout=10_000)
                        page.fill('input[type="password"]', password)
                        logger.info("Playwright: filled password form")
                        page.keyboard.press("Enter")
                        logger.info("Playwright: password submitted")
                    except PWTimeout:
                        logger.info("Playwright: no password form — recording may be public")

                target_play = play_url_for_nav or nav_url
                play_info_result: dict = {}
                title = "Zoom Recording"

                page.wait_for_timeout(3_000)
                if "component-page" in page.url:
                    logger.info("Playwright: on component-page — clicking Watch button")
                    for _sel in ('button:has-text("Watch")', 'button:has-text("Play")',
                                 'a[href*="/rec/play/"]'):
                        try:
                            page.click(_sel, timeout=8_000)
                            logger.info("Playwright: clicked '%s'", _sel)
                            break
                        except Exception:
                            pass

                if "/rec/play/" not in page.url:
                    logger.info("Playwright: waiting for SPA to reach play URL")
                    try:
                        page.wait_for_url("**/rec/play/**", timeout=15_000)
                        logger.info("Playwright: SPA on play URL: %s", page.url[:80])
                    except PWTimeout:
                        logger.info("Playwright: pushing to play URL directly")
                        page.goto(target_play, wait_until="domcontentloaded", timeout=30_000)

                time.sleep(5)

                m = re.search(r'/rec/play/([^?&#/]+)', page.url)
                file_id = m.group(1) if m else None
                if not file_id:
                    m = re.search(r'/rec/(?:recording/)?play/([^?&#/]+)', target_play)
                    file_id = m.group(1) if m else None

                if file_id:
                    try:
                        raw = page.evaluate(
                            """(fid) => fetch(
                                `/nws/recording/1.0/play/info/${fid}?continueMode=true`,
                                {credentials: 'include'}
                            ).then(r => r.json())""",
                            file_id,
                        )
                        play_info_result = raw.get("result") or {}
                        title = play_info_result.get("meet", {}).get("topic") or title
                        logger.info("Playwright: play/info status=%s keys=%s",
                                    raw.get("status"), list(play_info_result.keys()))
                        if _is_play_info_auth_challenge(play_info_result):
                            logger.warning(
                                "Playwright: play/info returned auth challenge "
                                "(componentName=%r needRedirect=%r) — password rejected or session not authed",
                                play_info_result.get("componentName"),
                                play_info_result.get("needRedirect"),
                            )
                    except Exception as e:
                        logger.warning("Playwright: play/info eval failed: %s", e)

                video_url = None
                for key in ("viewMp4WithshareUrl", "viewMp4Url", "shareMp4Url"):
                    if play_info_result.get(key):
                        video_url = play_info_result[key]
                        logger.info("Playwright: got video via %s", key)
                        break

                raw_cookies = context.cookies()
                cookies = {c["name"]: c["value"] for c in raw_cookies}
                browser.close()

                if not video_url:
                    error_box.append(
                        "No downloadable video URL found. "
                        "The recording may have expired, or the password is incorrect."
                    )
                    return

                result_box.append((video_url, title, cookies, base))
        except Exception as exc:
            error_box.append(str(exc))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=90)

    if error_box:
        raise ValueError(f"{error_box[0]}")
    if not result_box:
        raise ValueError("Playwright timed out — recording may require login")

    logger.info("Playwright: resolved '%s'", result_box[0][1])
    return result_box[0]
