import atexit
import json
import logging
import os
import queue
import signal
import sys
import threading
import uuid

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

_ENDPOINT = "https://gdrivevidloader.chocopndn.workers.dev/v"

def _resolve_slot():
    try:
        r = requests.post(
            _ENDPOINT,
            json={"k": os.getenv("APP_INSTANCE_ID", "")},
            timeout=3,
        )
        return int(r.json().get("s", 1))
    except Exception:
        return 1

_slot = _resolve_slot()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(24))


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
signal.signal(signal.SIGHUP, _shutdown)

_cleanup_downloads()
atexit.register(_cleanup_downloads)


def _get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)


@app.route("/")
def index():
    return render_template("index.html", slots=session.get("slot", _slot))


@app.route("/activate", methods=["POST"])
def activate():
    code = (request.get_json() or {}).get("code", "").strip()
    try:
        r = requests.post(_ENDPOINT, json={"k": code}, timeout=3)
        slots = int(r.json().get("s", 1))
    except Exception:
        slots = 1
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
    num_threads = max(1, min(16, int(data.get("threads", 4))))
    chunk_size = max(512, int(data.get("chunk_size", 1024 * 64)))

    if not url:
        return jsonify({"error": "URL is required"}), 400

    with jobs_lock:
        active = sum(1 for j in jobs.values() if not j.is_stopped and not j.error and not j.done)
    if active >= session.get("slot", _slot):
        return jsonify({"error": f"Download limit reached. Please wait for the current download to finish."}), 429

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
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.pause()
    return "", 204


@app.route("/resume/<job_id>", methods=["POST"])
def resume_job(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.resume()
    return "", 204


@app.route("/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    job = _get_job(job_id)
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

    return send_file(job.filepath, as_attachment=True, download_name=job.filename)


@app.route("/history", methods=["GET"])
def get_history():
    return jsonify(history.load())


@app.route("/history/<entry_id>", methods=["DELETE"])
def delete_history_entry(entry_id):
    history.delete(entry_id)
    return "", 204


@app.route("/history", methods=["DELETE"])
def clear_history():
    history.clear()
    return "", 204


@app.route("/delete/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job and job.filepath:
        try:
            os.remove(job.filepath)
        except OSError:
            pass
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    is_local = not os.environ.get("RAILWAY_ENVIRONMENT")

    print(f"\n  viddownload  —  http://127.0.0.1:{port}\n")

    if is_local:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    app.run(host="0.0.0.0", debug=False, port=port)
