import logging
import math
import os
import queue
import shutil
import threading
import time

import requests

from .gdrive import extract_drive_id, get_file_info, get_file_size, get_video_url, sanitize_filename
from . import history
from .job import Job
from .zoom import get_zoom_video_info
from converter import convert as gdocs_convert

logger = logging.getLogger(__name__)

PART_SIZE = 4 * 1024 * 1024  # 4 MB per part

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

FILE_TTL = 3600

jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()

active_job_ids: list[str] = []
active_job_ids_lock = threading.Lock()


def download_part_web(job, url, cookies, thread_lock, start, end, part_filename, chunk_size, progress_callback, extra_headers=None):
    headers = {"Range": f"bytes={start}-{end}"}
    if extra_headers:
        headers.update(extra_headers)
    downloaded = 0

    if os.path.exists(part_filename):
        downloaded = os.path.getsize(part_filename)
        if downloaded > 0:
            headers["Range"] = f"bytes={start + downloaded}-{end}"
            with thread_lock:
                progress_callback(downloaded)

    if downloaded >= (end - start + 1):
        return

    s = requests.Session()
    for attempt in range(5):
        response = s.get(url, stream=True, cookies=cookies, headers=headers)
        if response.status_code in (200, 206):
            break
        if response.status_code in (429, 503) and attempt < 4:
            wait = 2 ** attempt
            logger.warning("Part download got HTTP %s, retrying in %ss (attempt %d/5)...", response.status_code, wait, attempt + 1)
            time.sleep(wait)
            continue
        logger.error("Part download failed for %s — HTTP %s", part_filename, response.status_code)
        raise Exception(f"Failed to download part, status: {response.status_code}")

    file_mode = "ab" if os.path.exists(part_filename) and os.path.getsize(part_filename) > 0 else "wb"
    with open(part_filename, file_mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not job.wait_if_paused():
                return
            f.write(chunk)
            with thread_lock:
                progress_callback(len(chunk))
            downloaded += len(chunk)
            if downloaded >= (end - start + 1):
                break

    expected = end - start + 1
    if downloaded < expected:
        raise Exception(f"Part incomplete: got {downloaded}/{expected} bytes")


def download_file_web(job: Job, url, cookies, filepath, chunk_size, max_threads, extra_headers=None):
    total_size, _ = get_file_info(url, cookies, extra_headers)

    if total_size == 0:
        _download_file_web_single(job, url, cookies, filepath, chunk_size)
        return

    num_parts = math.ceil(total_size / PART_SIZE)
    part_files = [f"{filepath}.part{i}" for i in range(num_parts)]

    already = sum(os.path.getsize(pf) for pf in part_files if os.path.exists(pf))

    work_queue = queue.Queue()
    for i in range(num_parts):
        start = i * PART_SIZE
        end = min(start + PART_SIZE - 1, total_size - 1)
        expected = end - start + 1
        if not (os.path.exists(part_files[i]) and os.path.getsize(part_files[i]) >= expected):
            work_queue.put((i, start, end))

    errors = []
    thread_lock = threading.Lock()
    downloaded = already

    def progress_callback(n):
        nonlocal downloaded
        downloaded += n
        job.send({"type": "progress", "downloaded": downloaded, "total": total_size})

    def worker():
        while True:
            try:
                part_idx, start, end = work_queue.get(timeout=0.5)
            except queue.Empty:
                return
            if job.is_stopped:
                work_queue.task_done()
                return
            last_error = None
            for attempt in range(3):
                if job.is_stopped:
                    break
                try:
                    download_part_web(job, url, cookies, thread_lock, start, end,
                                      part_files[part_idx], chunk_size, progress_callback,
                                      extra_headers=extra_headers)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning("[job:%s] part %d attempt %d failed: %s", job.job_id, part_idx, attempt + 1, e)
                    try:
                        if os.path.exists(part_files[part_idx]):
                            os.remove(part_files[part_idx])
                    except OSError:
                        pass
                    if attempt < 2 and not job.is_stopped:
                        time.sleep(2 ** attempt)
            if last_error and not job.is_stopped:
                logger.error("[job:%s] part %d failed after 3 attempts: %s", job.job_id, part_idx, last_error)
                errors.append(last_error)
            work_queue.task_done()

    def current_rank():
        with active_job_ids_lock:
            try:
                return active_job_ids.index(job.job_id)
            except ValueError:
                return 0

    def target_threads():
        return max(1, max_threads >> current_rank())

    active_workers = []

    def scale_workers():
        target = target_threads()
        alive = sum(1 for t in active_workers if t.is_alive())
        while alive < target and not work_queue.empty():
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            active_workers.append(t)
            alive += 1

    scale_workers()
    while not work_queue.empty() or any(t.is_alive() for t in active_workers):
        if job.is_stopped:
            break
        scale_workers()
        time.sleep(0.5)
    for t in active_workers:
        t.join()

    if job.is_stopped:
        for pf in part_files:
            try:
                os.remove(pf)
            except OSError:
                pass
        return

    if errors:
        job.fail(f"Download error: {errors[0]}")
        return

    downloaded_total = sum(os.path.getsize(pf) for pf in part_files if os.path.exists(pf))
    if downloaded_total < total_size:
        job.fail(f"Download incomplete: got {downloaded_total}/{total_size} bytes.")
        return

    with open(filepath, "wb") as outfile:
        for part_file in part_files:
            with open(part_file, "rb") as pf:
                shutil.copyfileobj(pf, outfile)
    for pf in part_files:
        os.remove(pf)


def _download_file_web_single(job: Job, url, cookies, filepath, chunk_size):
    downloaded = 0
    headers = {}
    if os.path.exists(filepath):
        downloaded = os.path.getsize(filepath)
        headers["Range"] = f"bytes={downloaded}-"

    response = None
    for attempt in range(5):
        response = requests.get(url, stream=True, cookies=cookies, headers=headers)
        if response.status_code in (200, 206):
            break
        if response.status_code in (429, 503) and attempt < 4:
            wait = 2 ** attempt
            logger.warning("[job:%s] single-thread got HTTP %s, retrying in %ss (attempt %d/5)...", job.job_id, response.status_code, wait, attempt + 1)
            time.sleep(wait)
            continue
        logger.error("[job:%s] single-thread download failed — HTTP %s", job.job_id, response.status_code)
        job.fail(f"Download failed with status {response.status_code}")
        return

    total_size = int(response.headers.get("content-length", 0)) + downloaded
    with open(filepath, "ab" if downloaded else "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not job.wait_if_paused():
                return
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                job.send({"type": "progress", "downloaded": downloaded, "total": total_size})

    if total_size > 0 and downloaded < total_size:
        job.fail(f"Download incomplete: got {downloaded}/{total_size} bytes.")
        try:
            os.remove(filepath)
        except OSError:
            pass


def run_download(job_id, video_id_or_url, output_name, chunk_size, num_threads, user_id="", source="gdrive", password="", prefetched=None):
    with jobs_lock:
        job = jobs[job_id]

    if job.is_stopped:
        return

    with active_job_ids_lock:
        active_job_ids.append(job_id)
        rank = len(active_job_ids) - 1

    logger.info("[job:%s] starting %s download for %s (rank=%d)", job_id, source, video_id_or_url, rank)

    if source == "zoom":
        _run_zoom(job_id, job, video_id_or_url, password, chunk_size, num_threads, user_id, prefetched=prefetched)
    elif source == "gdocs":
        _run_gdocs(job_id, job, video_id_or_url, user_id)
    else:
        _run_gdrive(job_id, job, video_id_or_url, chunk_size, num_threads, user_id)

    with active_job_ids_lock:
        if job_id in active_job_ids:
            active_job_ids.remove(job_id)


def _run_gdocs(job_id, job, url, user_id):
    filepath = None
    try:
        job.send({"type": "queued"})
        job.send({"type": "status", "message": "Converting document..."})

        if job.is_stopped:
            return

        docx_bytes, doc_title = gdocs_convert(url)
        filename = sanitize_filename(doc_title or "document") + ".docx"
        filepath = os.path.join(DOWNLOADS_DIR, f"{job_id}_{filename}")
        with open(filepath, "wb") as f:
            f.write(docx_bytes)

        if job.is_stopped:
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass
            return

        logger.info("[job:%s] converted: %s", job_id, filename)
        job.finish(filepath, filename, FILE_TTL)
        history.append(filename, os.path.getsize(filepath), user_id)

    except Exception as e:
        if not job.is_stopped:
            logger.exception("[job:%s] gdocs error: %s", job_id, e)
            job.fail(str(e))


def _run_gdrive(job_id, job, video_id_or_url, chunk_size, num_threads, user_id):
    filepath = None
    try:
        job.send({"type": "queued"})

        video_id = extract_drive_id(video_id_or_url)
        drive_url = f"https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303"

        job.send({"type": "status", "message": "Fetching video info..."})
        if job.is_stopped:
            return

        response = requests.get(drive_url)
        cookies = response.cookies.get_dict()
        video, title = get_video_url(response.text)

        if not video:
            logger.warning("[job:%s] could not resolve video URL for %s", job_id, video_id_or_url)
            job.fail("Unable to retrieve video URL. Check that the link is correct and the file is publicly accessible.")
            return

        _, mime_ext = get_file_info(video, cookies)
        _, title_ext = os.path.splitext(title or "")
        drive_ext = title_ext or mime_ext

        filename = sanitize_filename(title or "video")
        if not os.path.splitext(filename)[1]:
            filename += drive_ext

        filepath = os.path.join(DOWNLOADS_DIR, f"{job_id}_{filename}")
        job.send({"type": "status", "message": f"Downloading: {filename}"})

        if job.is_stopped:
            return

        download_file_web(job, video, cookies, filepath, chunk_size, num_threads)

        if job.is_stopped:
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass
            return

        if not job.error:
            logger.info("[job:%s] finished: %s", job_id, filename)
            job.finish(filepath, filename, FILE_TTL)
            history.append(filename, os.path.getsize(filepath), user_id)

    except Exception as e:
        if not job.is_stopped:
            logger.exception("[job:%s] unexpected error: %s", job_id, e)
            job.fail(str(e))


def _run_zoom(job_id, job, share_url, password, chunk_size, num_threads, user_id, prefetched=None):
    filepath = None
    try:
        job.send({"type": "queued"})

        if prefetched:
            video_url, title, cookies, base_url = prefetched
        else:
            job.send({"type": "status", "message": "Authenticating with Zoom..."})
            if job.is_stopped:
                return
            video_url, title, cookies, base_url = get_zoom_video_info(share_url, password)

        extra_headers = {"Referer": base_url}
        filename = sanitize_filename(title or "zoom_recording") + ".mp4"
        filepath = os.path.join(DOWNLOADS_DIR, f"{job_id}_{filename}")

        job.send({"type": "status", "message": f"Downloading: {filename}"})

        if job.is_stopped:
            return

        download_file_web(job, video_url, cookies, filepath, chunk_size, num_threads, extra_headers=extra_headers)

        if job.is_stopped:
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except OSError:
                pass
            return

        if not job.error:
            logger.info("[job:%s] finished: %s", job_id, filename)
            job.finish(filepath, filename, FILE_TTL)
            history.append(filename, os.path.getsize(filepath), user_id)

    except Exception as e:
        if not job.is_stopped:
            logger.exception("[job:%s] zoom error: %s", job_id, e)
            job.fail(str(e))
