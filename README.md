# Notegrab

Downloads video recordings and documents from platforms that only let you stream or view them, not save them.

## Features

- Google Drive video download, multi-threaded with resume support
- Zoom cloud recording download, handles password-protected and login-gated recordings, falls back to a headless browser (Playwright) when the normal API is blocked
- Google Docs to .docx conversion
- Google Forms to .docx conversion, or extract into a flashcard/quiz set with an answer key
- Live progress bar, pause/resume/stop per download
- Files auto-delete 1 hour after a download finishes
- Per-session download history
- Save, edit, import/export flashcard sets

## Stack

Flask backend, vanilla JS frontend, requests for HTTP, python-docx for document generation, Playwright (Chromium) as the Zoom fallback.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium   # only needed for the Zoom fallback
```

Run it:

```bash
python app.py
```

Serves on http://localhost:8080 (also prints your LAN IP so you can hit it from another device).

## Configuration

All optional, set as environment variables:

- `SECRET_KEY`: Flask session signing key. Has an insecure default, set this yourself if you deploy it.
- `GITHUB_TOKEN` and `GIST_ID`: if both are set, flashcards and history get stored in a GitHub Gist instead of local files. Useful on hosts that wipe disk on redeploy.

## Project layout

```
app.py                Flask routes and job orchestration
core/
  downloader.py        chunked multi-thread download engine
  zoom.py               Zoom auth and video URL resolution, Playwright fallback
  gdrive.py               Drive video URL and metadata extraction
  job.py                    per-download job state (progress, pause/stop)
  history.py                 per-user download history
  flashcards.py                flashcard set storage
  gist_store.py                  optional GitHub Gist persistence
converter/
  builder.py, forms.py, ...  Google Docs/Forms to .docx conversion
  flashcard.py                 Forms question extraction
templates/, static/    frontend (HTML/CSS/JS)
```

## Notes

Downloaded files are temporary, cleaned up on process start/stop and 1 hour after a job finishes. Not affiliated with Google or Zoom, it just talks to the same endpoints their web apps use.
