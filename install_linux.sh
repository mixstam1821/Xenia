#!/usr/bin/env bash
# ── Xenia — Linux installer (uv) ─────────────────────────────────────────────
# Tested on Ubuntu 22.04 / 24.04 and Debian 12.
# Run once to install, then again any time to just start the server.
# Usage:
#   chmod +x install_linux.sh
#   ./install_linux.sh                        # uses ./data as data dir
#   MTG_DATA_DIR=/your/data ./install_linux.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CYAN="\033[0;36m"
GREEN="\033[0;32m"
RED="\033[0;31m"
NC="\033[0m"

log()  { echo -e "${CYAN}[xenia]${NC} $*"; }
ok()   { echo -e "${GREEN}[xenia]${NC} $*"; }
err()  { echo -e "${RED}[xenia]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${MTG_DATA_DIR:-$SCRIPT_DIR/data}"
PORT="${XENIA_PORT:-8994}"
PYTHON_VERSION="3.11"

log "Xenia installer — Linux"
log "Script dir : $SCRIPT_DIR"
log "Data dir   : $DATA_DIR"
log "Port       : $PORT"
echo

# ── 1. system dependencies ────────────────────────────────────────────────────
log "Checking system dependencies..."
MISSING_PKGS=()
for pkg in libhdf5-dev libnetcdf-dev libproj-dev libgdal-dev; do
    dpkg -s "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    log "Installing system packages: ${MISSING_PKGS[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends "${MISSING_PKGS[@]}"
fi
ok "System dependencies OK"

# ── 2. uv ─────────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # add to current session
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version)"

# ── 3. virtual environment ────────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment (Python $PYTHON_VERSION)..."
    uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
fi
ok "Virtual environment at $VENV_DIR"

# activate
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# ── 4. install Python packages ────────────────────────────────────────────────
log "Installing Python packages (this takes a few minutes the first time)..."
uv pip install \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.29" \
    "pydantic>=2.0" \
    "python-multipart" \
    "python-dotenv" \
    "numpy>=1.26" \
    "scipy>=1.12" \
    "xarray>=2024.1" \
    "netcdf4" \
    "h5py" \
    "h5netcdf" \
    "dask[distributed]" \
    "pyresample>=3.0" \
    "pyproj>=3.6" \
    "rasterio" \
    "matplotlib>=3.8" \
    "Pillow>=10.0" \
    "satpy[all]" \
    "uxarray" \
    "pycoast" \
    "trollimage" \
    "pyorbital" \
    "pykdtree"

ok "Python packages installed"

# ── 5. data directory ─────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
ok "Data directory: $DATA_DIR"

# ── 6. .env file ─────────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    log "Creating .env file..."
    cat > "$ENV_FILE" <<EOF
MTG_DATA_DIR=$DATA_DIR
EOF
else
    # update data dir in existing .env
    sed -i "s|^MTG_DATA_DIR=.*|MTG_DATA_DIR=$DATA_DIR|" "$ENV_FILE"
fi
ok ".env written"

# ── 7. launch ─────────────────────────────────────────────────────────────────
echo
ok "Starting Xenia on http://localhost:$PORT"
echo -e "${CYAN}  → Put your data files in: $DATA_DIR${NC}"
echo -e "${CYAN}  → Press Ctrl+C to stop${NC}"
echo

cd "$SCRIPT_DIR/backend"
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --no-access-log
