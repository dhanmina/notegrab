import atexit
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
import uuid
from datetime import timedelta

import requests
from flask import Flask, Response, jsonify, render_template, request, send_file, session

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from downloader import DOWNLOADS_DIR, jobs, jobs_lock, run_download
from gdrive import extract_drive_id, get_video_url
import history
from job import Job

def _load_seats() -> dict:
    try:
        return json.loads(os.getenv("SEAT_KEYS", "{}"))
    except Exception:
        return {}

def _resolve_slot() -> int:
    key = os.getenv("APP_INSTANCE_ID", "").upper()
    return _load_seats().get(key, 1)

_slot = _resolve_slot()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24))
app.permanent_session_lifetime = timedelta(days=30)


def _cleanup_downloads():
    for name in os.listdir(DOWNLOADS_DIR):
        if name == ".gitkeep":
            continue
        try:
            os.remove(os.path.join(DOWNLOADS_DIR, name))
        except OSError:
            pass


def _shutdown(signum, frame):
    _cleanup_downloads()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)

_cleanup_downloads()
atexit.register(_cleanup_downloads)

FILE_TTL = int(os.getenv("FILE_TTL_SECONDS", 3600))  # default 1 hour
CLEANUP_INTERVAL = 300  # check every 5 minutes

def _reap_expired_jobs():
    while True:
        time.sleep(CLEANUP_INTERVAL)
        now = time.monotonic()
        expired = []
        with jobs_lock:
            for job_id, job in list(jobs.items()):
                if job.finished_at and (now - job.finished_at) >= FILE_TTL:
                    expired.append(job_id)
                    jobs.pop(job_id)
        for job_id in expired:
            logger.info("[cleanup] removing expired job %s", job_id)
        # files are named {job_id}_* so we can match by prefix
        for name in os.listdir(DOWNLOADS_DIR):
            if name == ".gitkeep":
                continue
            job_id = name.split("_")[0]
            if job_id in expired:
                try:
                    os.remove(os.path.join(DOWNLOADS_DIR, name))
                    logger.info("[cleanup] deleted file %s", name)
                except OSError:
                    pass

threading.Thread(target=_reap_expired_jobs, daemon=True).start()


def _get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)


def _owns_job(job_id):
    return job_id in session.get("jobs", [])


def _user_id():
    return session.get("user_id", "")


@app.route("/")
def index():
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
        session.permanent = True
    return render_template("index.html")


@app.route("/config")
def config():
    return jsonify({"slots": session.get("slot", _slot)})


@app.route("/activate", methods=["POST"])
def activate():
    code = (request.get_json() or {}).get("code", "").strip().upper()
    slots = _load_seats().get(code, 1)
    session["slot"] = slots
    return jsonify({"slots": slots})


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
        _, title = get_video_url(response.text)
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
    max_threads = 16 if session.get("slot", _slot) >= 999 else 8
    num_threads = max(1, min(max_threads, int(data.get("threads", 8))))
    chunk_size = max(512, int(data.get("chunk_size", 1024 * 64)))

    if not url:
        return jsonify({"error": "URL is required"}), 400

    user_jobs = session.get("jobs", [])
    with jobs_lock:
        active = sum(1 for jid in user_jobs
                     if jid in jobs and not jobs[jid].is_stopped
                     and not jobs[jid].error and not jobs[jid].done)
    if active >= session.get("slot", _slot):
        return jsonify({"error": "Download limit reached. Please wait for the current download to finish."}), 429

    job_id = str(uuid.uuid4())
    job = Job(job_id)
    with jobs_lock:
        jobs[job_id] = job

    user_jobs.append(job_id)
    session["jobs"] = user_jobs
    session.modified = True

    logger.info("[job:%s] starting for %s", job_id, url)
    threading.Thread(
        target=run_download,
        args=(job_id, url, output, chunk_size, num_threads, _user_id()),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    if not _owns_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        while True:
            try:
                msg = job.events.get(timeout=30)
                yield f"data: {msg}\n\n"
                if json.loads(msg).get("type") in ("done", "error", "stopped"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream")


@app.route("/pause/<job_id>", methods=["POST"])
def pause_job(job_id):
    if not _owns_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.pause()
    return "", 204


@app.route("/resume/<job_id>", methods=["POST"])
def resume_job(job_id):
    if not _owns_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.resume()
    return "", 204


@app.route("/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    if not _owns_job(job_id):
        return jsonify({"error": "Job not found"}), 404
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.stop()
    return "", 204


@app.route("/download/<job_id>")
def download(job_id):
    if not _owns_job(job_id):
        return jsonify({"error": "File not found"}), 404
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.filepath or not os.path.exists(job.filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(job.filepath, as_attachment=True, download_name=job.filename)


@app.route("/history", methods=["GET"])
def get_history():
    return jsonify(history.load(_user_id()))


@app.route("/history/<entry_id>", methods=["DELETE"])
def delete_history_entry(entry_id):
    history.delete(entry_id, _user_id())
    return "", 204


@app.route("/history", methods=["DELETE"])
def clear_history():
    history.clear(_user_id())
    return "", 204


@app.route("/delete/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not _owns_job(job_id):
        return "", 204
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job and job.filepath:
        try:
            os.remove(job.filepath)
        except OSError:
            pass
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", debug=False, port=port)
