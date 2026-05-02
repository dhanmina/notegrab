import json
import logging
import math
import os
import queue
import re
import shutil
import threading
import time
import uuid

import requests
from flask import Flask, Response, after_this_request, jsonify, render_template, request, send_file

from gdrive_videoloader import extract_drive_id, get_file_size, get_video_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()

active_job_ids = []
active_job_ids_lock = threading.Lock()


class Job:
    def __init__(self, job_id):
        self.job_id = job_id
        self.events = queue.Queue()
        self.filepath = None
        self.filename = None
        self.done = False
        self.error = None
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._stopped = threading.Event()

    @property
    def is_stopped(self):
        return self._stopped.is_set()

    def pause(self):
        if not self.done:
            self._resume_event.clear()
            self.send({"type": "paused"})

    def resume(self):
        if not self.done:
            self._resume_event.set()
            self.send({"type": "resumed"})

    def stop(self):
        self._resume_event.set()
        self._stopped.set()
        if not self.done:
            self.done = True
            self.send({"type": "stopped"})

    def wait_if_paused(self):
        """Block while paused. Returns False if stopped."""
        self._resume_event.wait()
        return not self._stopped.is_set()

    def send(self, data: dict):
        self.events.put(json.dumps(data))

    def finish(self, filepath, filename):
        if self.done:
            return
        self.filepath = filepath
        self.filename = filename
        self.done = True
        self.send({"type": "done", "filename": filename})

    def fail(self, message):
        if self.done:
            return
        self.error = message
        self.done = True
        logger.error("[job:%s] failed: %s", self.job_id, message)
        self.send({"type": "error", "message": message})



def download_part_web(job, url, cookies, thread_lock, start, end, part_filename, chunk_size, progress_callback):
    headers = {"Range": f"bytes={start}-{end}"}
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


def download_file_web(job: Job, url, cookies, filepath, chunk_size, max_threads):
    total_size = get_file_size(url, cookies)

    if total_size == 0:
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
        return

    # Split file into small fixed-size parts for dynamic worker scaling
    PART_SIZE = 4 * 1024 * 1024  # 4 MB per part
    num_parts = math.ceil(total_size / PART_SIZE)
    part_files = [f"{filepath}.part{i}" for i in range(num_parts)]

    # Pre-count already downloaded bytes for resume
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
    downloaded_bytes = [already]

    def progress_callback(n):
        downloaded_bytes[0] += n
        job.send({"type": "progress", "downloaded": downloaded_bytes[0], "total": total_size})

    def worker():
        while True:
            try:
                part_idx, start, end = work_queue.get(timeout=0.5)
            except queue.Empty:
                return
            if job.is_stopped:
                work_queue.task_done()
                return
            try:
                download_part_web(job, url, cookies, thread_lock, start, end,
                                  part_files[part_idx], chunk_size, progress_callback)
            except Exception as e:
                logger.error("[job:%s] part %d error: %s", job.job_id, part_idx, e, exc_info=True)
                errors.append(e)
            finally:
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
            except Exception:
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


def run_download(job_id, video_id_or_url, output_name, chunk_size, num_threads):
    with jobs_lock:
        job = jobs[job_id]

    if job.is_stopped:
        return

    with active_job_ids_lock:
        active_job_ids.append(job_id)
        rank = len(active_job_ids) - 1

    logger.info("[job:%s] starting download for %s (rank=%d, max_threads=%d)", job_id, video_id_or_url, rank, num_threads)

    filepath = None
    try:
        video_id = extract_drive_id(video_id_or_url)
        drive_url = f"https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303"

        job.send({"type": "status", "message": "Fetching video info..."})

        if job.is_stopped:
            return

        response = requests.get(drive_url)
        cookies = response.cookies.get_dict()
        video, title = get_video_url(response.text, False)

        if not video:
            logger.warning("[job:%s] could not resolve video URL for %s", job_id, video_id_or_url)
            job.fail("Unable to retrieve video URL. Check that the link is correct and the file is publicly accessible.")
            return

        _, drive_ext = os.path.splitext(title or "")
        if output_name:
            _, user_ext = os.path.splitext(output_name)
            filename = output_name if user_ext else output_name + drive_ext
        else:
            filename = title
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", filename)
        filename = re.sub(r"[. ]+$", "", filename)

        filepath = os.path.join(DOWNLOADS_DIR, f"{job_id}_{filename}")
        job.send({"type": "status", "message": f"Downloading: {filename}"})

        if job.is_stopped:
            return

        download_file_web(job, video, cookies, filepath, chunk_size, num_threads)

        if job.is_stopped:
            try:
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass
            return

        if not job.error:
            logger.info("[job:%s] finished: %s", job_id, filename)
            job.finish(filepath, filename)

    except Exception as e:
        if not job.is_stopped:
            logger.exception("[job:%s] unexpected error: %s", job_id, e)
            job.fail(str(e))
    finally:
        with active_job_ids_lock:
            if job_id in active_job_ids:
                active_job_ids.remove(job_id)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
def info():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    try:
        video_id = extract_drive_id(url)
        drive_url = f"https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303"
        response = requests.get(drive_url, timeout=10)
        _, title = get_video_url(response.text, False)
        if not title:
            logger.warning("/info could not fetch title for %s", url)
            return jsonify({"error": "Could not fetch title"}), 400
        return jsonify({"title": title})
    except Exception as e:
        logger.exception("/info error for %s: %s", url, e)
        return jsonify({"error": str(e)}), 500


@app.route("/start", methods=["POST"])
def start():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    output = (data.get("output") or "").strip()
    num_threads = max(1, min(16, int(data.get("threads", 4))))
    chunk_size = max(512, int(data.get("chunk_size", 1024 * 64)))

    if not url:
        return jsonify({"error": "URL is required"}), 400

    job_id = str(uuid.uuid4())
    job = Job(job_id)
    with jobs_lock:
        jobs[job_id] = job

    logger.info("[job:%s] starting for %s", job_id, url)
    threading.Thread(
        target=run_download,
        args=(job_id, url, output, chunk_size, num_threads),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        while True:
            try:
                msg = job.events.get(timeout=30)
                yield f"data: {msg}\n\n"
                parsed = json.loads(msg)
                if parsed.get("type") in ("done", "error", "stopped"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream")


@app.route("/pause/<job_id>", methods=["POST"])
def pause_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.pause()
    return "", 204


@app.route("/resume/<job_id>", methods=["POST"])
def resume_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.resume()
    return "", 204


@app.route("/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.stop()
    return "", 204


@app.route("/download/<job_id>")
def download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.filepath or not os.path.exists(job.filepath):
        return jsonify({"error": "File not found"}), 404

    filepath = job.filepath
    filename = job.filename

    @after_this_request
    def cleanup(response):
        try:
            os.remove(filepath)
        except Exception:
            pass
        return response

    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route("/delete/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job and job.filepath:
        try:
            os.remove(job.filepath)
        except Exception:
            pass
    return "", 204


if __name__ == "__main__":
    import threading
    import webbrowser

    port = 5000
    url  = f"http://127.0.0.1:{port}"

    print(f"\n  viddownload")
    print(f"  ───────────────────────────")
    print(f"  Local:  {url}")
    print(f"\n  Opening browser...")
    print(f"  Press Ctrl+C to stop\n")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(debug=False, port=port)
