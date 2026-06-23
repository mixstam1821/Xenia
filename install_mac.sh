#!/usr/bin/env bash
# ── Xenia — macOS installer (uv) ─────────────────────────────────────────────
# Tested on macOS 13 Ventura and 14 Sonoma (Apple Silicon and Intel).
# Run once to install, then again any time to just start the server.
# Usage:
#   chmod +x install_mac.sh
#   ./install_mac.sh                          # uses ./data as data dir
#   MTG_DATA_DIR=/your/data ./install_mac.sh
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

log "Xenia installer — macOS"
log "Script dir : $SCRIPT_DIR"
log "Data dir   : $DATA_DIR"
log "Port       : $PORT"
echo

# ── 1. Homebrew ───────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    log "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple Silicon path
    [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
fi
ok "Homebrew $(brew --version | head -1)"

# ── 2. system libraries (HDF5, PROJ, GDAL) ────────────────────────────────────
log "Checking system libraries..."
for pkg in hdf5 netcdf proj gdal; do
    brew list "$pkg" &>/dev/null || {
        log "Installing $pkg via Homebrew..."
        brew install "$pkg"
    }
done
ok "System libraries OK"

# ── 3. uv ─────────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version)"

# ── 4. virtual environment ────────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment (Python $PYTHON_VERSION)..."
    uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
fi
ok "Virtual environment at $VENV_DIR"

# activate
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# ── 5. install Python packages ────────────────────────────────────────────────
log "Installing Python packages (this takes a few minutes the first time)..."

# On Apple Silicon, point compilers at Homebrew's HDF5/PROJ/GDAL
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    BREW_PREFIX="/opt/homebrew"
else
    BREW_PREFIX="/usr/local"
fi

export HDF5_DIR="$BREW_PREFIX"
export PROJ_DIR="$BREW_PREFIX"
export GDAL_CONFIG="$BREW_PREFIX/bin/gdal-config"

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

# ── 6. data directory ─────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
ok "Data directory: $DATA_DIR"

# ── 7. .env file ─────────────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    log "Creating .env file..."
    cat > "$ENV_FILE" <<EOF
MTG_DATA_DIR=$DATA_DIR
EOF
else
    # BSD sed on macOS needs an extension argument
    sed -i '' "s|^MTG_DATA_DIR=.*|MTG_DATA_DIR=$DATA_DIR|" "$ENV_FILE"
fi
ok ".env written"

# ── 8. open browser after a short delay ───────────────────────────────────────
(sleep 3 && open "http://localhost:$PORT") &

# ── 9. launch ─────────────────────────────────────────────────────────────────
echo
ok "Starting Xenia on http://localhost:$PORT"
echo -e "${CYAN}  → Put your data files in: $DATA_DIR${NC}"
echo -e "${CYAN}  → Browser will open automatically${NC}"
echo -e "${CYAN}  → Press Ctrl+C to stop${NC}"
echo

cd "$SCRIPT_DIR/backend"
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --no-access-log
