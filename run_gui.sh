#!/bin/bash

# Inferno GUI Launcher
# Runs the GUI with proper environment and root privileges

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUI_MODULE="inferno_gui"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log_error "Inferno GUI requires root privileges for PTP hardware timestamping."
    log_info "Re-launching with sudo..."
    exec sudo "$0" "$@"
fi

# Check if pip package is installed
if ! python3 -c "import inferno_gui" 2>/dev/null; then
    log_warn "inferno-gui package not installed."
    log_info "Installing in development mode..."
    cd "$SCRIPT_DIR"
    pip install -e . --quiet
fi

# Set up environment for PipeWire access
export XDG_RUNTIME_DIR="/run/user/$(id -u ${SUDO_USER:-$USER})"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

# Run the GUI
log_info "Starting Inferno GUI..."
cd "$SCRIPT_DIR"
exec python3 -m inferno_gui "$@"
