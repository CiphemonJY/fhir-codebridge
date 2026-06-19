#!/usr/bin/env bash
# fhir-codebridge Docker Quick Start
# ====================================
# Fastest way to try fhir-codebridge — Docker handles everything.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/CiphemonJY/fhir-codebridge/main/docker-quickstart.sh | bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║  fhir-codebridge Docker Quick Start           ║"
echo "  ║  FHIR Terminology Mapping Service v0.2.0      ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

# Check Docker
command -v docker >/dev/null 2>&1 || error "Docker required. Install from https://docker.com"
info "Docker detected ✓"

# Clone
INSTALL_DIR="${1:-$(pwd)/fhir-codebridge}"
if [ ! -d "$INSTALL_DIR/.git" ]; then
  info "Cloning repository..."
  git clone --quiet https://github.com/CiphemonJY/fhir-codebridge.git "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
info "Repository ready ✓"

# Generate API key
API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || echo "changeme-$(date +%s)")

# Create .env
cat > .env << EOF
CODEBRIDGE_API_KEYS=${API_KEY}:admin
CODEBRIDGE_PORT=8000
EOF
info "Admin API key: ${API_KEY}"

# Build and start
info "Building Docker image..."
docker compose build --quiet

info "Starting service..."
docker compose up -d

# Wait for health check
info "Waiting for service to start..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    info "Service is healthy ✓"
    break
  fi
  sleep 2
  if [ $i -eq 15 ]; then
    warn "Service didn't respond in 30s. Check: docker compose logs"
  fi
done

echo ""
info "══════════════════════════════════════════════════"
info "  fhir-codebridge is running!"
info ""
info "  Health:  http://localhost:8000/health"
info "  Docs:    http://localhost:8000/docs"
info "  API Key: ${API_KEY}"
info ""
info "  Test it:"
info "    curl -H 'X-API-Key: ${API_KEY}' http://localhost:8000/stats"
info ""
info "  Stop:    docker compose down"
info "  Logs:    docker compose logs -f"
info "══════════════════════════════════════════════════"
echo ""