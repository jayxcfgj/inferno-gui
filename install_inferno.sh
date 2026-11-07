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
WORK_DIR="$HOME/audio-inferno"
INFERNO_DIR="$WORK_DIR/inferno"
STATIME_DIR="$WORK_DIR/statime"
ALSA_PLUGIN_DIR="/usr/lib/x86_64-linux-gnu/alsa-lib"
ASOUNDRC="$HOME/.asoundrc"

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

    if ! prompt_yes_no "Continue with installation?" "y"; then
        log_info "Installation cancelled by user."
        exit 0
    fi

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

    # Step 12: Optional - netaudio
    step_optional_netaudio

    # Step 13: Optional - Cable
    step_optional_cable

    # Step 14: Optional - Millisecond
    step_optional_millisecond

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
    run_cmd "cd ~ && git clone https://gitlab.freedesktop.org/pipewire/pipewire.git"
    run_cmd "cd ~/pipewire && ./autogen.sh --prefix=/usr"
    run_cmd "cd ~/pipewire && make -j$(nproc)"
    run_cmd_sudo "cd ~/pipewire && make install"
    
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
    run_cmd "git clone --recurse-submodules -b inferno-dev https://github.com/teodly/statime \"$STATIME_DIR\""
    
    log_info "Cloning inferno..."
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

step_configure_statime() {
    log_step "Step 7: Configuring statime (PTP)"
    
    local iface
    iface=$(cat "$WORK_DIR/selected_interface.txt")
    
    # PTP version selection
    local ptp_version
    ptp_version=$(prompt_select "Select PTP version for clock synchronization:" "PTPv2 (IEEE 1588-2008, recommended)" "PTPv1 (IEEE 1588-2002)")
    
    if [[ "$ptp_version" == "PTPv1"* ]]; then
        CONFIG_FILE="inferno-ptpv1.toml"
        PTP_VERSION_FLAG="v1"
    else
        CONFIG_FILE="inferno-ptpv2.toml"
        PTP_VERSION_FLAG="v2"
    fi
    
    log_info "Configuring $CONFIG_FILE for interface $iface..."
    
    run_cmd "cd \"$STATIME_DIR\""
    
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
        run_cmd "aplay -L | grep -i inferno"
    fi
    
    # Test plugin listing
    log_info "Testing ALSA plugin detection..."
    run_cmd "aplay -L | grep -i inferno"
}

step_configure_alsa() {
    log_step "Step 10: Configuring ALSA (.asoundrc)"
    
    local iface
    iface=$(cat "$WORK_DIR/selected_interface.txt")
    local ip_addr
    ip_addr=$(cat "$WORK_DIR/selected_ip.txt" 2>/dev/null || echo "")
    
    echo
    log_info "Configure inferno audio parameters:"
    
    local sample_rate
    sample_rate=$(prompt_input "Sample rate" "48000")
    
    local tx_channels
    tx_channels=$(prompt_input "TX channels (output to network)" "24")
    
    local rx_channels
    rx_channels=$(prompt_input "RX channels (input from network)" "24")
    
    local bind_ip
    if [ -n "$ip_addr" ]; then
        bind_ip=$(prompt_input "Bind IP address" "$ip_addr")
    else
        bind_ip=$(prompt_input "Bind IP address (interface IP)" "$iface")
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
    
    local override_dir="$HOME/.config/systemd/user/pipewire.service.d"
    local override_file="$override_dir/override.conf"
    
    run_cmd "mkdir -p \"$override_dir\""
    
    cat > "$override_file" << 'EOF'
[Service]
SystemCallFilter=@clock
EOF
    
    log_success "Created PipeWire override: $override_file"
    
    if [ "$TEST_MODE" = false ]; then
        log_info "Restarting PipeWire services..."
        run_cmd "systemctl --user restart pipewire"
        run_cmd "systemctl --user restart wireplumber"
        sleep 2
        run_cmd "systemctl --user status pipewire --no-pager"
    else
        log_info "[DRY-RUN] Would restart PipeWire services"
    fi
    
    log_warn "Note: A reboot or re-login may be required for PipeWire changes to take full effect."
}

step_optional_netaudio() {
    log_step "Step 12: Optional - netaudio (Dante Controller)"
    
    if ! prompt_yes_no "Install netaudio for Dante network routing control?" "y"; then
        log_info "Skipping netaudio installation"
        return 0
    fi
    
    log_info "netaudio installation options:"
    echo "  1) Install via cargo (from source)"
    echo "  2) Download pre-built binary (if available)"
    echo "  3) Install via package manager (if packaged)"
    
    local choice
    choice=$(prompt_select "Select installation method:" "cargo (from source)" "Download binary" "Package manager")
    
    case "$choice" in
        "cargo (from source)")
            log_info "Installing netaudio via cargo..."
            run_cmd "cargo install netaudio"
            run_cmd "cargo install netaudio-daemon"
            ;;
        "Download binary")
            log_info "Checking for pre-built releases..."
            run_cmd "curl -s https://api.github.com/repos/teodly/netaudio/releases/latest | grep browser_download_url | head -1"
            log_warn "Manual download required - visit https://github.com/teodly/netaudio/releases"
            ;;
        "Package manager")
            log_warn "netaudio may not be available in standard repositories yet"
            ;;
    esac
    
    # Daemon setup
    if prompt_yes_no "Set up netaudio-daemon as systemd service (auto-start)?" "y"; then
        local service_file="/etc/systemd/system/netaudio-daemon.service"
        if [ "$TEST_MODE" = true ]; then
            log_info "[TEST MODE] Would create systemd service: $service_file"
            log_info "[TEST MODE] Would run: systemctl daemon-reload && systemctl enable netaudio-daemon && systemctl start netaudio-daemon"
        else
            cat > "$service_file" << 'EOF'
[Unit]
Description=netaudio daemon for Dante/AES67 control
After=network.target pipewire.service
Wants=pipewire.service

[Service]
Type=simple
ExecStart=/usr/local/bin/netaudio-daemon
Restart=on-failure
User=%i

[Install]
WantedBy=multi-user.target
EOF
            run_cmd_sudo "systemctl daemon-reload"
            run_cmd_sudo "systemctl enable netaudio-daemon"
            run_cmd_sudo "systemctl start netaudio-daemon"
        fi
        log_success "netaudio-daemon installed and started"
    fi
}

step_optional_cable() {
    log_step "Step 13: Optional - Cable (PipeWire GUI)"
    
    log_info "Cable is a graphical PipeWire patchbay/routing tool."
    log_info "Recommended installation: Download .deb package from GitHub releases"
    log_info "URL: https://github.com/magillos/Cable/releases"
    
    if prompt_yes_no "Open Cable releases page in browser?" "y"; then
        run_cmd "xdg-open https://github.com/magillos/Cable/releases 2>/dev/null || echo 'Please visit: https://github.com/magillos/Cable/releases'"
    fi
    
    if prompt_yes_no "Download and install latest Cable .deb package now?" "n"; then
        log_info "This would require manual version selection. Please download from the releases page."
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
    run_cmd "cd ~ && git clone https://github.com/gaheldev/Millisecond.git"
    run_cmd "cd ~/Millisecond && meson setup build/"
    run_cmd_sudo "cd ~/Millisecond && meson install -C build/"
    
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