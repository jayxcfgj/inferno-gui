#!/bin/bash

# =============================================================================
# Inferno Installation Script
# =============================================================================
# This script automates the installation and configuration of inferno
# (a Dante virtual soundcard alternative for Linux) along with its dependencies.
#
# The script will:
# 1. Update system packages
# 2. Check/install PipeWire >= 1.1
# 3. Install required system packages
# 4. Install Rust toolchain
# 5. Build statime (PTP daemon) and inferno (ALSA plugin)
# 6. Configure network interface for PTP
# 7. Configure statime (PTPv1/PTPv2)
# 8. Configure inferno ALSA plugin
# 9. Configure PipeWire for inferno
# 10. Optionally install netaudio (Dante controller) and Cable (PipeWire GUI)
# 11. Optionally install Millisecond (realtime tuning tool)
#
# Usage: sudo ./install_inferno.sh [--test-mode]
#   --test-mode  : Replace system-altering commands with dry-run placeholders
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script configuration
TEST_MODE=false

# Determine actual user's home directory (handles sudo correctly)
# Use parameter expansion to avoid 'unbound variable' error with set -u
SUDO_USER_VAL="${SUDO_USER:-}"
if [ -n "$SUDO_USER_VAL" ] && [ "$SUDO_USER_VAL" != "root" ]; then
    ACTUAL_HOME=$(getent passwd "$SUDO_USER_VAL" | cut -d: -f6 2>/dev/null || echo "$HOME")
else
    ACTUAL_HOME="$HOME"
fi

WORK_DIR="$ACTUAL_HOME/audio-inferno"
INFERNO_DIR="$WORK_DIR/inferno"
STATIME_DIR="$WORK_DIR/statime"
ALSA_PLUGIN_DIR="/usr/lib/x86_64-linux-gnu/alsa-lib"
ASOUNDRC="$ACTUAL_HOME/.asoundrc"

# Parse arguments
for arg in "$@"; do
    case $arg in
        --test-mode)
            TEST_MODE=true
            echo -e "${YELLOW}[TEST MODE] System-altering commands will be simulated${NC}"
            ;;
        --help|-h)
            echo "Usage: $0 [--test-mode]"
            echo "  --test-mode  Run in test mode (dry-run, no system changes)"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "\n${CYAN}==== $* ====${NC}\n"; }

run_cmd() {
    if [ "$TEST_MODE" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $*"
        return 0
    else
        log_info "Running: $*"
        bash -c "$*"
    fi
}

run_cmd_sudo() {
    if [ "$TEST_MODE" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} sudo $*"
        return 0
    else
        log_info "Running (sudo): $*"
        sudo bash -c "$*"
    fi
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local response
    
    if [ "$TEST_MODE" = true ]; then
        # In test mode, always use default
        echo "$prompt [Y/n]: $default (auto-selected in test mode)" >&2
        case $default in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
        esac
    fi
    
    if [ "$default" = "y" ]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi
    
    while true; do
        read -rp "$prompt" response
        response=${response:-$default}
        case $response in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "Please answer yes or no." >&2 ;;
        esac
    done
}

prompt_select() {
    local prompt="$1"
    shift
    local options=("$@")
    local response
    
    if [ "$TEST_MODE" = true ]; then
        # In test mode, auto-select first option
        echo "$prompt" >&2
        for i in "${!options[@]}"; do
            echo "  $((i+1))) ${options[i]}" >&2
        done
        echo "Select option [1-${#options[@]}]: 1 (auto-selected in test mode)" >&2
        echo "${options[0]}"
        return 0
    fi
    
    echo "$prompt" >&2
    for i in "${!options[@]}"; do
        echo "  $((i+1))) ${options[i]}" >&2
    done
    
    while true; do
        read -rp "Select option [1-${#options[@]}]: " response
        if [[ "$response" =~ ^[0-9]+$ ]] && [ "$response" -ge 1 ] && [ "$response" -le "${#options[@]}" ]; then
            echo "${options[$((response-1))]}"
            return 0
        fi
        echo "Invalid selection. Please enter a number between 1 and ${#options[@]}." >&2
    done
}

prompt_input() {
    local prompt="$1"
    local default="${2:-}"
    local response
    
    if [ "$TEST_MODE" = true ]; then
        # In test mode, use default
        if [ -n "$default" ]; then
            echo "$prompt [$default]: $default (auto-selected in test mode)" >&2
            echo "$default"
        else
            echo "$prompt: (auto-skipped in test mode)" >&2
            echo ""
        fi
        return 0
    fi
    
    if [ -n "$default" ]; then
        read -rp "$prompt [$default]: " response
        echo "${response:-$default}"
    else
        read -rp "$prompt: " response
        echo "$response"
    fi
}

# =============================================================================
# MAIN INSTALLATION FLOW
# =============================================================================

# Fetch latest release info from GitHub API
fetch_latest_release() {
    local repo="$1"
    local api_url="https://api.github.com/repos/$repo/releases/latest"
    local version
    # Use python for robust JSON parsing
    version=$(curl -s "$api_url" 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('tag_name', ''))" 2>/dev/null)
    if [ -z "$version" ]; then
        version=$(curl -s "$api_url" 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('name', ''))" 2>/dev/null)
    fi
    echo "$version"
}

# Fetch latest release asset URL
fetch_latest_asset_url() {
    local repo="$1"
    local pattern="$2"
    local api_url="https://api.github.com/repos/$repo/releases/latest"
    local url
    # Use python for robust JSON parsing
    url=$(curl -s "$api_url" 2>/dev/null | python3 -c "
import sys, json, re
data = json.load(sys.stdin)
pattern = re.compile(r'$pattern')
for asset in data.get('assets', []):
    if pattern.search(asset.get('browser_download_url', '')):
        print(asset['browser_download_url'])
        break
" 2>/dev/null)
    echo "$url"
}

main() {
    clear
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════════════════╗
║                    Inferno Installation Script                              ║
║         Dante Virtual Soundcard Alternative for Linux                       ║
╚═════════════════════════════════════════════════════════════════════════════╝

This script will install and configure:
  • PipeWire (>= 1.1) - Audio server
  • statime           - PTP/IEEE 1588 daemon (Rust)
  • inferno           - ALSA plugin for Dante/AES67 audio
  • Optional: netaudio, Cable, Millisecond

Root privileges are required for system package installation and configuration.
EOF

    if [ "$EUID" -ne 0 ] && [ "$TEST_MODE" = false ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi

    # Main menu
    echo
    echo "Select installation mode:"
    echo "  1) Full installation (Inferno + Optional tools)"
    echo "  2) Inferno only (skip optional tools)"
    echo "  3) Optional tools only (skip Inferno - requires existing inferno setup)"
    echo "  4) Custom selection"
    echo
    local mode
    mode=$(prompt_select "Choose installation mode:" "Full installation" "Inferno only" "Optional tools only" "Custom selection")

    local install_inferno=false
    local install_optional=false
    local install_netaudio=false
    local install_cable=false
    local install_millisecond=false

    case "$mode" in
        "Full installation")
            install_inferno=true
            install_optional=true
            install_netaudio=true
            install_cable=true
            install_millisecond=true
            ;;
        "Inferno only")
            install_inferno=true
            ;;
        "Optional tools only")
            install_optional=true
            install_netaudio=true
            install_cable=true
            install_millisecond=true
            ;;
        "Custom selection")
            install_inferno=$(prompt_yes_no "Install Inferno (statime, inferno plugin, PipeWire config)?" "y" && echo "true" || echo "false")
            install_netaudio=$(prompt_yes_no "Install netaudio (Dante controller)?" "y" && echo "true" || echo "false")
            install_cable=$(prompt_yes_no "Install Cable (PipeWire GUI)?" "y" && echo "true" || echo "false")
            install_millisecond=$(prompt_yes_no "Install Millisecond (realtime tuning)?" "y" && echo "true" || echo "false")
            if [ "$install_netaudio" = "true" ] || [ "$install_cable" = "true" ] || [ "$install_millisecond" = "true" ]; then
                install_optional=true
            fi
            ;;
    esac

    if [ "$install_inferno" = "false" ] && [ "$install_optional" = "false" ]; then
        log_info "Nothing selected. Exiting."
        exit 0
    fi

    # Step 1-11: Inferno core installation
    if [ "$install_inferno" = "true" ]; then
        # Step 1: System Update
        step_system_update

        # Step 2: PipeWire Check/Install
        step_pipewire

        # Step 3: Required Packages
        step_required_packages

        # Step 4: Rust Toolchain
        step_rust

        # Step 5: Build statime and inferno
        step_build_statime_inferno

        # Step 6: Network Interface Selection
        step_network_interface

        # Step 7: Configure statime
        step_configure_statime

        # Step 8: Build inferno ALSA plugin
        step_build_inferno_plugin

        # Step 9: Install ALSA plugin
        step_install_alsa_plugin

        # Step 10: Configure ALSA (.asoundrc)
        step_configure_alsa

        # Step 11: Configure PipeWire for inferno
        step_configure_pipewire
    fi

    # Step 12-14: Optional tools
    if [ "$install_optional" = "true" ]; then
        if [ "$install_netaudio" = "true" ]; then
            step_optional_netaudio
        fi
        if [ "$install_cable" = "true" ]; then
            step_optional_cable
        fi
        if [ "$install_millisecond" = "true" ]; then
            step_optional_millisecond
        fi
    fi

    log_success "Installation complete!"
    show_summary
}

# =============================================================================
# STEP FUNCTIONS
# =============================================================================

step_system_update() {
    log_step "Step 1: System Update"
    run_cmd_sudo "apt-get update"
    if prompt_yes_no "Upgrade all packages? (recommended)" "y"; then
        run_cmd_sudo "apt-get upgrade -y"
    fi
    log_success "System update complete"
}

step_pipewire() {
    log_step "Step 2: PipeWire Version Check"
    
    local pw_version
    if [ "$TEST_MODE" = true ]; then
        # In test mode, simulate an older version to test the build flow
        pw_version="0.3"
        log_info "[TEST MODE] Simulating PipeWire version: $pw_version"
    else
        # Search all output lines for version pattern (version is on line 2/3, not line 1)
        pw_version=$(pipewire --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    fi
    
    if [ -z "$pw_version" ]; then
        log_warn "PipeWire not found"
        pw_version="0.0"
    fi
    
    log_info "Detected PipeWire version: $pw_version"
    
    # Compare version with 1.1
    local major minor
    major=$(echo "$pw_version" | cut -d. -f1)
    minor=$(echo "$pw_version" | cut -d. -f2)
    
    if [ "$major" -gt 1 ] || { [ "$major" -eq 1 ] && [ "$minor" -ge 1 ]; }; then
        log_success "PipeWire >= 1.1 is already installed"
        return 0
    fi
    
    log_warn "PipeWire version is older than 1.1 (current: $pw_version)"
    log_info "Building PipeWire from source requires development packages and takes several minutes."
    
    if ! prompt_yes_no "Build and install latest PipeWire from source?" "y"; then
        log_info "Skipping PipeWire build. Note: inferno may not work correctly with PipeWire < 1.1"
        return 0
    fi
    
    log_step "Installing PipeWire build dependencies"
    run_cmd_sudo "apt-get install -y \
        build-essential gcc g++ make git meson ninja-build pkg-config \
        python3 python3-pip python3-setuptools python3-wheel \
        libtool autoconf automake cmake gettext \
        libglib2.0-dev libasound2-dev libdbus-1-dev libudev-dev \
        libsystemd-dev libpulse-dev libbluetooth-dev libusb-1.0-0-dev \
        libsndfile1-dev libsbc-dev libopus-dev libfftw3-dev \
        libavcodec-dev libavformat-dev libavutil-dev libavfilter-dev \
        libswscale-dev libswresample-dev \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        libva-dev libv4l-dev libdrm-dev \
        libx11-dev libxfixes-dev libxrandr-dev \
        libwayland-dev libegl1-mesa-dev libgbm-dev \
        libjack-jackd2-dev libsamplerate0-dev libspeexdsp-dev \
        libflac-dev libvorbis-dev libogg-dev \
        liblilv-dev libsord-dev libserd-dev libsratom-dev"
    
    log_step "Cloning and building PipeWire"
    # Remove existing directory to allow clean clone
    if [ "$TEST_MODE" = false ] && [ -d "$ACTUAL_HOME/pipewire" ]; then
        log_info "Removing existing pipewire directory..."
        rm -rf "$ACTUAL_HOME/pipewire"
    fi
    run_cmd "cd "$ACTUAL_HOME" && git clone https://gitlab.freedesktop.org/pipewire/pipewire.git"
    run_cmd "cd "$ACTUAL_HOME/pipewire" && ./autogen.sh --prefix=/usr"
    run_cmd "cd "$ACTUAL_HOME/pipewire" && make -j$(nproc)"
    run_cmd_sudo "cd "$ACTUAL_HOME/pipewire" && make install"
    
    log_step "Restarting PipeWire services"
    run_cmd "systemctl --user restart pipewire wireplumber"
    sleep 2
    
    local new_version
    if [ "$TEST_MODE" = true ]; then
        new_version="1.2"
        log_info "[TEST MODE] Simulating PipeWire version: $new_version"
    else
        new_version=$(pipewire --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    fi
    log_success "PipeWire updated to version: $new_version"
}

step_required_packages() {
    log_step "Step 3: Installing Required System Packages"
    run_cmd_sudo "apt-get install -y git build-essential libasound2-dev pkg-config qpwgraph curl ca-certificates alsa-utils"
    log_success "Required packages installed"
}

step_rust() {
    log_step "Step 4: Installing Rust Toolchain"
    
    if command -v cargo &> /dev/null; then
        log_info "Rust is already installed: $(cargo --version)"
        if ! prompt_yes_no "Reinstall/update Rust toolchain?" "n"; then
            return 0
        fi
    fi
    
    log_info "Installing rustup..."
    run_cmd "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
    run_cmd "source \"\$HOME/.cargo/env\""
    
    # Add to current shell
    export PATH="$HOME/.cargo/bin:$PATH"
    
    if [ "$TEST_MODE" = true ]; then
        log_success "Rust installed: cargo 1.80.0 (simulated)"
    else
        log_success "Rust installed: $(cargo --version)"
    fi
}

step_build_statime_inferno() {
    log_step "Step 5: Downloading and Building statime & inferno"
    
    run_cmd "mkdir -p \"$WORK_DIR\""
    run_cmd "cd \"$WORK_DIR\""
    
    log_info "Cloning statime (inferno-dev branch)..."
    # Remove existing directory to allow clean clone
    if [ "$TEST_MODE" = false ] && [ -d "$STATIME_DIR" ]; then
        log_info "Removing existing statime directory..."
        rm -rf "$STATIME_DIR"
    fi
    run_cmd "git clone --recurse-submodules -b inferno-dev https://github.com/teodly/statime \"$STATIME_DIR\""
    
    log_info "Cloning inferno..."
    if [ "$TEST_MODE" = false ] && [ -d "$INFERNO_DIR" ]; then
        log_info "Removing existing inferno directory..."
        rm -rf "$INFERNO_DIR"
    fi
    run_cmd "git clone --recursive https://github.com/teodly/inferno \"$INFERNO_DIR\""
    
    log_step "Building statime..."
    run_cmd "cd \"$STATIME_DIR\" && cargo build"
    
    if [ "$TEST_MODE" = true ] || [ -f "$STATIME_DIR/target/debug/statime" ]; then
        log_success "statime built successfully"
        if [ "$TEST_MODE" = false ]; then
            ls -lh "$STATIME_DIR/target/debug/statime"
        else
            echo "[TEST MODE] Simulated binary at $STATIME_DIR/target/debug/statime"
        fi
    else
        log_error "statime build failed - binary not found"
        exit 1
    fi
}

step_network_interface() {
    log_step "Step 6: Network Interface Selection"
    
    log_info "Available network interfaces:"
    if [ "$TEST_MODE" = true ]; then
        # Simulate interfaces in test mode
        echo "  eth0  UP  192.168.1.100/24"
        echo "  enp3s0  UP  10.0.0.50/24"
        interfaces=("eth0" "enp3s0")
    else
        ip -br addr | grep -v "lo " | while read -r line; do
            echo "  $line"
        done
        
        # Get list of interfaces (excluding loopback)
        local interfaces=()
        while IFS= read -r line; do
            iface=$(echo "$line" | awk '{print $1}')
            [ -n "$iface" ] && interfaces+=("$iface")
        done < <(ip -br link | grep -v "lo " | awk '{print $1}')
        
        if [ ${#interfaces[@]} -eq 0 ]; then
            log_error "No network interfaces found (excluding loopback)"
            exit 1
        fi
    fi
    
    echo
    log_info "Note: This can be changed later in the statime config files or by re-running the script."
    SELECTED_IFACE=$(prompt_select "Select the network interface for Dante/PTP:" "${interfaces[@]}")
    log_success "Selected interface: $SELECTED_IFACE"
    
    # Get IP address for selected interface
    SELECTED_IP=$(ip -br addr show "$SELECTED_IFACE" 2>/dev/null | awk '{print $3}' | cut -d/ -f1 | head -1) || true
    log_info "IP address for $SELECTED_IFACE: ${SELECTED_IP:-"(not assigned)"}"
    
    # Save for later steps
    if [ "$TEST_MODE" = true ]; then
        mkdir -p "$WORK_DIR"
    fi
    echo "$SELECTED_IFACE" > "$WORK_DIR/selected_interface.txt"
    echo "$SELECTED_IP" > "$WORK_DIR/selected_ip.txt"
}

# Create default statime config file if missing
create_statime_config() {
    local config_file="$1"
    local ptp_version="$2"
    
    if [[ "$ptp_version" == "v1" ]]; then
        cat > "$config_file" << 'TOMLEOF'
# statime PTPv1 configuration for Inferno
# IEEE 1588-2002

[global]
domain = 0
interface = "eth0"
log_level = "info"

[port]
sync_interval = 0
announce_interval = 1
announce_receipt_timeout = 3
delay_mechanism = "E2E"
TOMLEOF
    else
        cat > "$config_file" << 'TOMLEOF'
# statime PTPv2 configuration for Inferno
# IEEE 1588-2008

[global]
domain = 0
interface = "eth0"
log_level = "info"
two_step_flag = true

[port]
sync_interval = 0
announce_interval = 1
announce_receipt_timeout = 3
delay_mechanism = "E2E"
TOMLEOF
    fi
    log_success "Created default $config_file"
}

step_configure_statime() {
    log_step "Step 7: Configuring statime (PTP)"
    
    local iface
    iface=$(cat "$WORK_DIR/selected_interface.txt")
    
    # PTP version selection - no default recommendation
    local ptp_version
    log_info "Note: This can be changed later by re-running the script or editing the statime config files."
    ptp_version=$(prompt_select "Select PTP version for clock synchronization:" "PTPv1 (IEEE 1588-2002)" "PTPv2 (IEEE 1588-2008)")
    
    if [[ "$ptp_version" == "PTPv1"* ]]; then
        CONFIG_FILE="inferno-ptpv1.toml"
        PTP_VERSION_FLAG="v1"
    else
        CONFIG_FILE="inferno-ptpv2.toml"
        PTP_VERSION_FLAG="v2"
    fi
    
    log_info "Configuring $CONFIG_FILE for interface $iface..."
    
    run_cmd "cd \"$STATIME_DIR\""
    
    # Ensure config file exists (create from template if needed)
    if [ "$TEST_MODE" = false ] && [ ! -f "$CONFIG_FILE" ]; then
        log_info "Config file $CONFIG_FILE not found, creating default..."
        create_statime_config "$CONFIG_FILE" "$PTP_VERSION_FLAG"
    fi
    
    # Update interface in config file
    if [ "$TEST_MODE" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would update interface in $CONFIG_FILE to $iface"
    else
        # Use sed to replace interface line
        if grep -q "^interface" "$CONFIG_FILE"; then
            sed -i "s/^interface = .*/interface = \"$iface\"/" "$CONFIG_FILE"
        else
            # Add interface if not present (after first line or in appropriate section)
            sed -i "2i interface = \"$iface\"" "$CONFIG_FILE"
        fi
        log_success "Updated $CONFIG_FILE with interface: $iface"
    fi
    
    # Create start script
    local start_script="$WORK_DIR/start-statime.sh"
    cat > "$start_script" << EOF
#!/bin/bash
# Auto-generated statime start script
cd "$STATIME_DIR"
sudo ./target/debug/statime -c "$STATIME_DIR/$CONFIG_FILE"
EOF
    chmod +x "$start_script"
    log_success "Created start script: $start_script"
    
    # Save PTP version choice
    echo "$PTP_VERSION_FLAG" > "$WORK_DIR/ptp_version.txt"
    echo "$CONFIG_FILE" > "$WORK_DIR/statime_config.txt"
}

step_build_inferno_plugin() {
    log_step "Step 8: Building inferno ALSA Plugin"
    
    run_cmd "cd \"$INFERNO_DIR/alsa_pcm_inferno\" && cargo build"
    
    local plugin_path="$INFERNO_DIR/target/debug/libasound_module_pcm_inferno.so"
    if [ "$TEST_MODE" = true ] || [ -f "$plugin_path" ]; then
        log_success "inferno ALSA plugin built successfully"
        if [ "$TEST_MODE" = false ]; then
            ls -lh "$plugin_path"
        else
            echo "[TEST MODE] Simulated binary at $plugin_path"
        fi
    else
        log_error "inferno plugin build failed - binary not found at $plugin_path"
        exit 1
    fi
}

step_install_alsa_plugin() {
    log_step "Step 9: Installing ALSA Plugin"
    
    local plugin_src="$INFERNO_DIR/target/debug/libasound_module_pcm_inferno.so"
    local plugin_dst="$ALSA_PLUGIN_DIR/libasound_module_pcm_inferno.so"
    
    # Check ALSA plugin directory
    if [ "$TEST_MODE" = false ] && [ ! -d "$ALSA_PLUGIN_DIR" ]; then
        log_warn "ALSA plugin directory not found: $ALSA_PLUGIN_DIR"
        log_info "Trying alternative locations..."
        # Try to find the correct directory
        local alt_dirs=(
            "/usr/lib/alsa-lib"
            "/usr/lib64/alsa-lib"
            "/usr/local/lib/alsa-lib"
        )
        for d in "${alt_dirs[@]}"; do
            if [ -d "$d" ]; then
                ALSA_PLUGIN_DIR="$d"
                plugin_dst="$ALSA_PLUGIN_DIR/libasound_module_pcm_inferno.so"
                log_info "Found ALSA plugin directory: $ALSA_PLUGIN_DIR"
                break
            fi
        done
    elif [ "$TEST_MODE" = true ]; then
        log_info "[TEST MODE] Using default ALSA plugin directory: $ALSA_PLUGIN_DIR"
    fi
    
    # Remove any existing inferno plugin (symlink or regular file) before installing new one
    if [ "$TEST_MODE" = false ]; then
        if [ -L "$plugin_dst" ] || [ -f "$plugin_dst" ]; then
            log_info "Removing existing inferno ALSA plugin at $plugin_dst"
            run_cmd_sudo "rm -f \"$plugin_dst\""
        fi
    else
        log_info "[TEST MODE] Would remove existing ALSA plugin at $plugin_dst"
    fi
    
    run_cmd_sudo "ln -sf \"$plugin_src\" \"$plugin_dst\""
    
    if [ "$TEST_MODE" = false ]; then
        if [ -L "$plugin_dst" ] && [ -e "$plugin_dst" ]; then
            log_success "ALSA plugin installed at $plugin_dst"
            ls -l "$plugin_dst"
        else
            log_error "Failed to create symlink for ALSA plugin"
            exit 1
        fi
    else
        log_success "[DRY-RUN] Would install ALSA plugin to $plugin_dst"
    fi
    
    # Test plugin listing
    log_info "Testing ALSA plugin detection..."
    if [ "$TEST_MODE" = true ]; then
        run_cmd "aplay -L | grep -i inferno"
    else
        # grep returns 1 if no matches, don't fail script
        run_cmd "aplay -L | grep -i inferno || true"
    fi
}

step_configure_alsa() {
    log_step "Step 10: Configuring ALSA (.asoundrc)"
    
    local iface
    iface=$(cat "$WORK_DIR/selected_interface.txt")
    local ip_addr
    ip_addr=$(cat "$WORK_DIR/selected_ip.txt" 2>/dev/null || echo "")
    
    echo
    log_info "Configure inferno audio parameters:"
    log_info "Note: These can be changed later by editing ~/.asoundrc"
    
    local sample_rate
    sample_rate=$(prompt_input "Sample rate" "48000")
    
    local tx_channels
    tx_channels=$(prompt_input "TX channels (output to network)" "24")
    
    local rx_channels
    rx_channels=$(prompt_input "RX channels (input from network)" "24")
    
    local bind_ip
    # Auto-detect IP from interface, use as default
    if [ -n "$ip_addr" ]; then
        bind_ip="$ip_addr"
        log_info "Auto-detected bind IP for $iface: $bind_ip"
    else
        log_warn "No IP assigned to $iface, using interface name as bind address"
        bind_ip="$iface"
    fi
    log_info "Note: This can be changed later by editing ~/.asoundrc"
    # Allow override if needed
    if prompt_yes_no "Use detected bind IP ($bind_ip)?" "y"; then
        :  # Keep detected IP
    else
        bind_ip=$(prompt_input "Enter custom bind IP address" "$bind_ip")
    fi
    
    local device_name
    device_name=$(prompt_input "Device name" "Inferno")
    
    log_info "Writing $ASOUNDRC..."
    
    cat > "$ASOUNDRC" << EOF
pcm.inferno {
    type inferno

    NAME "$device_name"
    SAMPLE_RATE "$sample_rate"

    TX_CHANNELS $tx_channels
    RX_CHANNELS $rx_channels

    BIND_IP "$bind_ip"

    hint {
        show on
        description "Inferno Dante Virtual Soundcard"
    }
}
EOF
    
    log_success "Created $ASOUNDRC"
    log_info "You can modify this file later to change audio parameters."
}

step_configure_pipewire() {
    log_step "Step 11: Configuring PipeWire for inferno"
    
    local override_dir="$ACTUAL_HOME/.config/systemd/user/pipewire.service.d"
    local override_file="$override_dir/override.conf"
    
    run_cmd "mkdir -p \"$override_dir\""
    
    cat > "$override_file" << 'EOF'
[Service]
SystemCallFilter=@clock
EOF
    
    # Fix ownership if running as root
    if [ "$TEST_MODE" = false ] && [ -n "$SUDO_USER_VAL" ] && [ "$SUDO_USER_VAL" != "root" ]; then
        chown -R "$SUDO_USER_VAL:$SUDO_USER_VAL" "$ACTUAL_HOME/.config/systemd/user/pipewire.service.d" 2>/dev/null || true
    fi
    
    log_success "Created PipeWire override: $override_file"
    
    if [ "$TEST_MODE" = false ]; then
        log_info "Restarting PipeWire services (as user $SUDO_USER_VAL)..."
        if [ -n "$SUDO_USER_VAL" ] && [ "$SUDO_USER_VAL" != "root" ]; then
            # Run systemctl --user as the actual user
            run_cmd_sudo "sudo -u $SUDO_USER_VAL XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER_VAL) systemctl --user restart pipewire"
            run_cmd_sudo "sudo -u $SUDO_USER_VAL XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER_VAL) systemctl --user restart wireplumber"
        else
            run_cmd "systemctl --user restart pipewire"
            run_cmd "systemctl --user restart wireplumber"
        fi
        sleep 2
        if [ -n "$SUDO_USER_VAL" ] && [ "$SUDO_USER_VAL" != "root" ]; then
            run_cmd_sudo "sudo -u $SUDO_USER_VAL XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER_VAL) systemctl --user status pipewire --no-pager"
        else
            run_cmd "systemctl --user status pipewire --no-pager"
        fi
    else
        log_info "[DRY-RUN] Would restart PipeWire services"
    fi
    
    log_warn "Note: A reboot or re-login may be required for PipeWire changes to take full effect."
}

step_optional_netaudio() {
    log_step "Step 12: Optional - netaudio (Dante Controller alternative)"
    
    if ! prompt_yes_no "Install netaudio for Dante network routing control?" "y"; then
        log_info "Skipping netaudio installation"
        return 0
    fi
    
    log_info "Fetching latest netaudio release..."
    local latest_version
    latest_version=$(fetch_latest_release "chris-ritsen/network-audio-controller")
    if [ -n "$latest_version" ]; then
        log_info "Latest netaudio version: $latest_version"
    else
        log_warn "Could not fetch latest version, will install latest from PyPI"
    fi
    
    log_info "netaudio installation options:"
    echo "  1) Install via pipx (recommended - isolated environment for CLI tools)"
    echo "  2) Build from source (requires Rust)"
    echo "  3) Skip installation"
    
    local choice
    choice=$(prompt_select "Select installation method:" "pipx install (recommended)" "Build from source" "Skip")
    
    case "$choice" in
        "pipx install (recommended)")
            log_info "Installing netaudio via pipx (isolated environment)..."
            # Ensure pipx is installed
            if ! command -v pipx &> /dev/null; then
                log_info "pipx not found, installing..."
                run_cmd_sudo "apt-get install -y pipx"
                run_cmd "pipx ensurepath"
            fi
            run_cmd "pipx install --force netaudio"
            log_info "netaudio includes CLI, daemon, and web UI"
            ;;
        "Build from source")
            log_info "Building netaudio from source..."
            # Check for Rust/Cargo (required for building)
            if ! command -v cargo &> /dev/null; then
                log_warn "Rust/Cargo not found. Installing Rust toolchain for user $SUDO_USER_VAL..."
                if [ -n "$SUDO_USER_VAL" ] && [ "$SUDO_USER_VAL" != "root" ]; then
                    # Run entire pipeline as target user (wrap in bash -c to ensure pipe runs as user)
                    run_cmd_sudo "sudo -H -u $SUDO_USER_VAL bash -c 'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y'"
                    run_cmd_sudo "sudo -H -u $SUDO_USER_VAL bash -c 'source "$ACTUAL_HOME/.cargo/env" && export PATH="$ACTUAL_HOME/.cargo/bin:\$PATH"'"
                    export PATH="$ACTUAL_HOME/.cargo/bin:$PATH"
                else
                    run_cmd "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"
                    run_cmd "source "$ACTUAL_HOME/.cargo/env""
                    export PATH="$ACTUAL_HOME/.cargo/bin:$PATH"
                fi
            fi
            
            # Install build dependencies (JACK, ALSA, PulseAudio development libraries)
            log_info "Installing build dependencies for netaudio (JACK, ALSA, PulseAudio)..."
            run_cmd_sudo "apt-get install -y libjack-jackd2-dev libasound2-dev libpulse-dev libdbus-1-dev pkg-config"
            
            # Remove existing directory if present
            if [ "$TEST_MODE" = false ] && [ -d "$ACTUAL_HOME/network-audio-controller" ]; then
                log_info "Removing existing network-audio-controller directory..."
                rm -rf "$ACTUAL_HOME/network-audio-controller"
            fi
            run_cmd "cd "$ACTUAL_HOME" && git clone https://github.com/chris-ritsen/network-audio-controller.git"
            # Build and install with pipx (avoids externally-managed-environment)
            # First ensure pipx is available
            if ! command -v pipx &> /dev/null; then
                log_info "pipx not found, installing..."
                run_cmd_sudo "apt-get install -y pipx"
                run_cmd "pipx ensurepath"
            fi
            # Install from local source using pipx (isolated environment)
            run_cmd "cd "$ACTUAL_HOME/network-audio-controller" && pipx install --force ."
            log_info "Built and installed from source via pipx (isolated environment)"
            ;;
        "Skip")
            log_info "Skipping netaudio installation"
            ;;
    esac
    
    # Daemon setup
    if prompt_yes_no "Set up netaudio-daemon as systemd service (auto-start)?" "y"; then
        local service_file="/etc/systemd/system/netaudio-daemon.service"
        local netaudio_daemon_path
        # Find netaudio-daemon binary location (pipx installs to ~/.local/bin)
        if [ -f "$ACTUAL_HOME/.local/bin/netaudio-daemon" ]; then
            netaudio_daemon_path="$ACTUAL_HOME/.local/bin/netaudio-daemon"
        elif [ -f "$ACTUAL_HOME/.local/bin/netaudio" ]; then
            # netaudio might have daemon as subcommand
            netaudio_daemon_path="$ACTUAL_HOME/.local/bin/netaudio daemon"
        elif command -v netaudio-daemon &> /dev/null; then
            netaudio_daemon_path=$(command -v netaudio-daemon)
        else
            netaudio_daemon_path="/usr/local/bin/netaudio-daemon"
        fi
        
        if [ "$TEST_MODE" = true ]; then
            log_info "[TEST MODE] Would create systemd service: $service_file"
            log_info "[TEST MODE] Daemon path: $netaudio_daemon_path"
            log_info "[TEST MODE] Would run: systemctl daemon-reload && systemctl enable netaudio-daemon && systemctl start netaudio-daemon"
        else
            cat > "$service_file" << EOF
[Unit]
Description=netaudio daemon for Dante/AES67 control
After=network.target pipewire.service
Wants=pipewire.service

[Service]
Type=simple
ExecStart=$netaudio_daemon_path
Restart=on-failure
User=$SUDO_USER_VAL
Environment=PATH=$ACTUAL_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF
            run_cmd_sudo "systemctl daemon-reload"
            run_cmd_sudo "systemctl enable netaudio-daemon"
            run_cmd_sudo "systemctl start netaudio-daemon"
            sleep 2
            
            # Show web UI address and offer to open browser
            log_info "Getting netaudio daemon web interface address..."
            local web_url
            web_url=$(sudo -u "$SUDO_USER_VAL" XDG_RUNTIME_DIR=/run/user/$(id -u "$SUDO_USER_VAL") PATH="$ACTUAL_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" netaudio daemon web 2>/dev/null | grep -oE 'https?://[^ ]+' | head -1)
            if [ -n "$web_url" ]; then
                log_success "netaudio web UI available at: $web_url"
                if prompt_yes_no "Open netaudio web UI in default browser?" "y"; then
                    log_info "Opening web UI in browser..."
                    sudo -u "$SUDO_USER_VAL" XDG_RUNTIME_DIR=/run/user/$(id -u "$SUDO_USER_VAL") PATH="$ACTUAL_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" netaudio daemon web --open
                fi
            else
                log_warn "Could not determine web UI address. Default is usually http://localhost:8777"
                log_info "Try running: netaudio daemon web"
            fi
        fi
        log_success "netaudio-daemon installed and started"
    fi
}

step_optional_cable() {
    log_step "Step 13: Optional - Cable (PipeWire GUI)"
    
    log_info "Fetching latest Cable release..."
    local latest_version
    latest_version=$(fetch_latest_release "magillos/Cable")
    if [ -n "$latest_version" ]; then
        log_info "Latest Cable version: $latest_version"
    else
        log_warn "Could not fetch latest version"
    fi
    
    log_info "Cable is a graphical PipeWire patchbay/routing tool."
    log_info "Recommended installation: Download .deb package from GitHub releases"
    log_info "URL: https://github.com/magillos/Cable/releases"
    
    if prompt_yes_no "Open Cable releases page in browser?" "y"; then
        run_cmd "xdg-open https://github.com/magillos/Cable/releases 2>/dev/null || echo 'Please visit: https://github.com/magillos/Cable/releases'"
    fi
    
    if prompt_yes_no "Download and install latest Cable .deb package now?" "n"; then
        log_info "Fetching latest .deb download URL..."
        local deb_url
        deb_url=$(fetch_latest_asset_url "magillos/Cable" "\.deb$")
        if [ -n "$deb_url" ]; then
            log_info "Downloading: $deb_url"
            run_cmd "cd /tmp && wget -q "$deb_url" -O cable_latest.deb && sudo dpkg -i cable_latest.deb"
            log_success "Cable installed"
        else
            log_warn "Could not find .deb asset. Please download manually from releases page."
        fi
    fi
}

step_optional_millisecond() {
    log_step "Step 14: Optional - Millisecond (Realtime Tuning)"
    
    log_info "Millisecond helps tune your system for realtime/low-latency audio."
    log_info "GitHub: https://github.com/gaheldev/Millisecond"
    
    if ! prompt_yes_no "Install Millisecond?" "y"; then
        log_info "Skipping Millisecond. Consider running it manually later for optimal performance."
        return 0
    fi
    
    log_step "Installing Millisecond dependencies"
    run_cmd_sudo "apt-get install -y meson ninja-build build-essential python3-all"
    run_cmd_sudo "apt-get install -y libgtk-4-dev libadwaita-1-dev python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 adwaita-icon-theme"
    
    log_step "Building Millisecond from source"
    # Remove existing directory if present
    if [ "$TEST_MODE" = false ] && [ -d "$ACTUAL_HOME/Millisecond" ]; then
        log_info "Removing existing Millisecond directory..."
        rm -rf "$ACTUAL_HOME/Millisecond"
    fi
    run_cmd "cd "$ACTUAL_HOME" && git clone https://github.com/gaheldev/Millisecond.git"
    run_cmd "cd "$ACTUAL_HOME/Millisecond" && meson setup build/"
    run_cmd_sudo "cd "$ACTUAL_HOME/Millisecond" && meson install -C build/"
    
    if prompt_yes_no "Run Millisecond now to optimize system?" "y"; then
        run_cmd "millisecond"
    fi
}

show_summary() {
    log_step "Installation Summary"
    
    cat << EOF

${GREEN}✓ Installation Complete!${NC}

${CYAN}Next Steps:${NC}
1. ${YELLOW}Reboot or re-login${NC} to ensure all PipeWire changes take effect
2. Start statime (PTP daemon):
   ${BLUE}$WORK_DIR/start-statime.sh${NC}
3. Verify inferno device appears:
   ${BLUE}aplay -L | grep inferno${NC}
4. In your audio software (DAW, etc.), select "Inferno" as audio device
5. Use netaudio-web (if installed) for Dante routing: http://localhost:8080

${CYAN}Configuration Files:${NC}
  • statime config: $STATIME_DIR/$(cat "$WORK_DIR/statime_config.txt" 2>/dev/null || echo "inferno-ptpv2.toml")
  • ALSA config: $ASOUNDRC
  • PipeWire override: $HOME/.config/systemd/user/pipewire.service.d/override.conf
  • Selected interface: $(cat "$WORK_DIR/selected_interface.txt" 2>/dev/null || echo "N/A")
  • PTP version: $(cat "$WORK_DIR/ptp_version.txt" 2>/dev/null || echo "v2")

${CYAN}Useful Commands:${NC}
  • Start PTP:     $WORK_DIR/start-statime.sh
  • Test ALSA:     aplay -L | grep inferno
  • PipeWire logs: journalctl --user -u pipewire -f
  • netaudio web:  http://localhost:8080 (if installed)

${YELLOW}For realtime performance:${NC}
  • Run 'millisecond' to tune system settings
  • Ensure your user is in 'realtime' group: sudo usermod -a -G realtime \$USER
  • Check /etc/security/limits.d/audio.conf for realtime limits

EOF
}

# Run main
main "$@"