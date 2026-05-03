#!/bin/bash
cd "$(dirname "$0")"

if ! python3 -c "import flask, requests, tqdm, dotenv" 2>/dev/null; then
  echo "Installing requirements..."
  python3 -m pip install -r requirements.txt
fi

python3 app.py
