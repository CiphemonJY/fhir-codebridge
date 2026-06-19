#!/usr/bin/env bash
# fhir-codebridge Quick Start Installer
# =======================================
# Clones, installs, and starts the service in under 5 minutes.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/CiphemonJY/fhir-codebridge/main/quickstart.sh | bash
#
# Or clone and run locally:
#   ./quickstart.sh

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Config ---
REPO_URL="https://github.com/CiphemonJY/fhir-codebridge.git"
INSTALL_DIR="${1:-$(pwd)/fhir-codebridge}"
PORT="${CODEBRIDGE_PORT:-8000}"

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║  fhir-codebridge Quick Start Installer        ║"
echo "  ║  FHIR Terminology Mapping Service v0.4.1      ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

# --- Check prerequisites ---
info "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || error "Python 3.10+ required. Install from https://python.org"
command -v git >/dev/null 2>&1 || error "Git required. Install from https://git-scm.com"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python $PYTHON_VERSION detected ✓"
info "Git detected ✓"

# Check Python version >= 3.10
python3 -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null || \
  warn "Python 3.10+ recommended (you have $PYTHON_VERSION). Some features may not work."

# --- Clone or update ---
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Updating existing install at $INSTALL_DIR..."
  cd "$INSTALL_DIR"
  git pull --quiet
else
  info "Cloning fhir-codebridge to $INSTALL_DIR..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
info "Repository ready ✓"

# --- Create virtualenv ---
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  info "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi
# Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
info "Virtual environment active ✓"

# --- Install dependencies ---
info "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
info "Dependencies installed ✓"

# --- Create .env from example ---
if [ ! -f "$INSTALL_DIR/.env" ]; then
  info "Creating .env from template..."
  cp .env.example .env
  
  # Generate random API key
  API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(16))")
  sed -i.bak "s/changeme-admin-key:admin,changeme-readonly-key:read/${API_KEY}:admin/" .env
  rm -f .env.bak
  info "Admin API key generated: ${API_KEY}"
  warn "Save this key! You'll need it for API calls."
  echo ""
  echo "  API Key: ${API_KEY}"
  echo ""
else
  info "Existing .env found, keeping current settings"
fi

# --- Run tests ---
info "Running integration tests..."
if python3 -m pytest tests/ -q 2>&1; then
  info "All tests passed ✓"
else
  warn "Some tests failed. The service may still work, but please check."
fi

# --- Start service ---
echo ""
info "══════════════════════════════════════════════════"
info "  Starting fhir-codebridge on port $PORT..."
info "  Health check: http://localhost:$PORT/health"
info "  API docs:     http://localhost:$PORT/docs"
info ""
info "  Press Ctrl+C to stop."
info "══════════════════════════════════════════════════"
echo ""

python3 -m uvicorn scripts.api.server:app --host 0.0.0.0 --port "$PORT"