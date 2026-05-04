import json
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

class Job:
    def __init__(self, job_id):
        self.job_id = job_id
        self.events = queue.Queue()
        self.filepath = None
        self.filename = None
        self.done = False
        self.error = None
        self.finished_at = None
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
            self.finished_at = time.monotonic()
            self.send({"type": "stopped"})

    def wait_if_paused(self):
        self._resume_event.wait()
        return not self._stopped.is_set()

    def send(self, data: dict):
        self.events.put(json.dumps(data))

    def finish(self, filepath, filename, ttl=3600):
        if self.done:
            return
        self.filepath = filepath
        self.filename = filename
        self.done = True
        self.finished_at = time.monotonic()
        self.send({"type": "done", "filename": filename, "ttl": ttl})

    def fail(self, message):
        if self.done:
            return
        self.error = message
        self.done = True
        self.finished_at = time.monotonic()
        logger.error("[job:%s] failed: %s", self.job_id, message)
        self.send({"type": "error", "message": message})
