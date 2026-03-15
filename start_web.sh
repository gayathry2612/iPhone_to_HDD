#!/usr/bin/env bash
# start_web.sh — launch the iPhone Transfer web UI
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"

# ── Ensure venv exists ────────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "Virtual environment not found. Run ./install.sh first."
  exit 1
fi

# ── Activate venv ─────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# ── Install new deps if needed ────────────────────────────────────────────────
pip install fastapi "uvicorn[standard]" --quiet

# ── Launch ────────────────────────────────────────────────────────────────────
echo ""
echo "  iPhone Transfer — Web UI"
echo "  ═══════════════════════════════"
echo "  Open in browser:  http://${HOST}:${PORT}"
echo "  Press Ctrl+C to stop."
echo ""

# Open browser automatically (macOS)
sleep 1 && open "http://${HOST}:${PORT}" &

cd "$SCRIPT_DIR"
python -m uvicorn web.server:app --host "$HOST" --port "$PORT" --reload
