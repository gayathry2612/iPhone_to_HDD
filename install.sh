#!/usr/bin/env bash
# install.sh — one-time setup for iPhone Transfer Tool
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✗${NC}  $*"; exit 1; }

echo ""
echo "  iPhone → Mac File Transfer — Setup"
echo "  ======================================"
echo ""

# ── 1. Python 3.10+ ──────────────────────────────────────────────────────────
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
  fail "python3 not found. Install it from https://www.python.org or via Homebrew: brew install python"
fi

PY_VERSION=$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  fail "Python 3.10 or newer is required (found $PY_VERSION). Upgrade with: brew install python"
fi
ok "Python $PY_VERSION"

# ── 2. libimobiledevice (usbmuxd) via Homebrew ───────────────────────────────
if ! command -v brew &>/dev/null; then
  warn "Homebrew not found — skipping native library check."
  warn "If you see USB errors, install Homebrew (https://brew.sh) then run:"
  warn "  brew install libimobiledevice usbmuxd"
else
  for pkg in libimobiledevice usbmuxd; do
    if brew list "$pkg" &>/dev/null; then
      ok "$pkg (already installed)"
    else
      echo "  Installing $pkg via Homebrew…"
      brew install "$pkg"
      ok "$pkg"
    fi
  done
fi

# ── 3. Python virtual environment ────────────────────────────────────────────
VENV_DIR="$(dirname "$0")/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "  Creating virtual environment…"
  "$PY" -m venv "$VENV_DIR"
  ok "Virtual environment created at .venv/"
else
  ok "Virtual environment already exists"
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Upgrade pip silently
pip install --upgrade pip --quiet

# ── 4. Python dependencies ────────────────────────────────────────────────────
echo "  Installing Python dependencies…"
pip install -r "$(dirname "$0")/requirements.txt" --quiet
ok "Python dependencies installed"

# ── 5. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "  Setup complete!"
echo ""
echo "  To launch the TUI:"
echo "    source .venv/bin/activate"
echo "    python main.py"
echo ""
echo "  Or run directly:"
echo "    .venv/bin/python main.py"
echo ""
echo "  Other commands:"
echo "    python main.py list                              # show device info"
echo "    python main.py transfer /DCIM /Volumes/MyHDD    # headless transfer"
echo ""
