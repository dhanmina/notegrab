import logging
import re
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)


def extract_drive_id(input_str: str) -> str:
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', input_str)
    return match.group(1) if match else input_str


def get_video_url(page_content: str) -> tuple[str, str]:
    content_list = page_content.split("&")
    video, title = None, None
    for content in content_list:
        if content.startswith('title=') and not title:
            title = unquote(content.split('=')[-1])
        elif "videoplayback" in content and not video:
            video = unquote(content).split("|")[-1]
        if video and title:
            break
    logger.debug("Resolved video URL: %s, title: %s", video, title)
    return video, title


def get_file_size(url: str, cookies: dict) -> int:
    response = requests.head(url, cookies=cookies, allow_redirects=True)
    return int(response.headers.get('content-length', 0))


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '', name)
    return re.sub(r'[. ]+$', '', name)
