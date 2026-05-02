import json
import math
import os
import queue
import re
import shutil
import threading
import uuid

import requests
from flask import Flask, Response, after_this_request, jsonify, render_template, request, send_file

from gdrive_videoloader import extract_drive_id, get_file_size, get_video_url

app = Flask(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()


class Job:
    def __init__(self, job_id):
        self.job_id = job_id
        self.events = queue.Queue()
        self.filepath = None
        self.filename = None
        self.done = False
        self.error = None

    def send(self, data: dict):
        self.events.put(json.dumps(data))

    def finish(self, filepath, filename):
        self.filepath = filepath
        self.filename = filename
        self.done = True
        self.send({"type": "done", "filename": filename})

    def fail(self, message):
        self.error = message
        self.done = True
        self.send({"type": "error", "message": message})


def download_part_web(url, cookies, thread_lock, start, end, part_filename, chunk_size, progress_callback):
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
    response = s.get(url, stream=True, cookies=cookies, headers=headers)
    if response.status_code not in (200, 206):
        raise Exception(f"Failed to download part, status: {response.status_code}")

    file_mode = "ab" if os.path.exists(part_filename) and os.path.getsize(part_filename) > 0 else "wb"
    with open(part_filename, file_mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            with thread_lock:
                progress_callback(len(chunk))
            downloaded += len(chunk)
            if downloaded >= (end - start + 1):
                break


def download_file_web(job: Job, url, cookies, filepath, chunk_size, num_threads):
    total_size = get_file_size(url, cookies)
    errors = []

    if num_threads == 1 or total_size == 0:
        downloaded = 0
        headers = {}
        if os.path.exists(filepath):
            downloaded = os.path.getsize(filepath)
            headers["Range"] = f"bytes={downloaded}-"

        response = requests.get(url, stream=True, cookies=cookies, headers=headers)
        if response.status_code not in (200, 206):
            job.fail(f"Download failed with status {response.status_code}")
            return

        if not total_size:
            total_size = int(response.headers.get("content-length", 0)) + downloaded

        with open(filepath, "ab" if downloaded else "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    job.send({"type": "progress", "downloaded": downloaded, "total": total_size})
        return

    part_size = math.ceil(total_size / num_threads)
    part_files = [f"{filepath}.part{i}" for i in range(num_threads)]
    threads = []
    thread_lock = threading.Lock()
    downloaded_bytes = [0]

    def progress_callback(n):
        downloaded_bytes[0] += n
        job.send({"type": "progress", "downloaded": downloaded_bytes[0], "total": total_size})

    def part_wrapper(*args):
        try:
            download_part_web(*args)
        except Exception as e:
            errors.append(e)

    for i in range(num_threads):
        start = i * part_size
        end = min(start + part_size - 1, total_size - 1)
        t = threading.Thread(
            target=part_wrapper,
            args=(url, cookies, thread_lock, start, end, part_files[i], chunk_size, progress_callback),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

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

    try:
        video_id = extract_drive_id(video_id_or_url)
        drive_url = f"https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303"

        job.send({"type": "status", "message": "Fetching video info..."})

        response = requests.get(drive_url)
        cookies = response.cookies.get_dict()
        video, title = get_video_url(response.text, False)

        if not video:
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

        filepath = os.path.join(DOWNLOADS_DIR, filename)
        job.send({"type": "status", "message": f"Downloading: {filename}"})

        download_file_web(job, video, cookies, filepath, chunk_size, num_threads)

        if not job.error:
            job.finish(filepath, filename)

    except Exception as e:
        job.fail(str(e))


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
            return jsonify({"error": "Could not fetch title"}), 400
        return jsonify({"title": title})
    except Exception as e:
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
                if parsed.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream")


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
