# PipeWire Cleanup Integration Plan

## Overview
Integrate the `pipewire-cleanup.sh` functionality into the existing `install_inferno.sh` installer, following the existing architecture, using existing helpers, and maintaining the step-wise structure.

## Existing Architecture Analysis

### Installer Structure (`install_inferno.sh`)
- **Step-wise functions**: `step_system_update()`, `step_pipewire()`, `step_required_packages()`, `step_build_*`, `step_optional_*`, `step_optional_gui()`
- **Helper functions**:
  - `run_as_user()` - user-context execution with TEST_MODE, sudo -H -u, XDG_RUNTIME_DIR, direct fallback
  - `run_cmd_sudo()` - root-context execution with TEST_MODE
  - `run_cmd()` - general execution with TEST_MODE
  - `prompt_yes_no()` - yes/no prompting with TEST_MODE
  - `log_step()`, `log_info()`, `log_success()`, `log_warn()`, `log_error()` - logging
- **Key variables**: `TEST_MODE`, `SUDO_USER_VAL`, `ACTUAL_HOME`, `WORK_DIR`, `STATIME_DIR`, `INFERNO_DIR`
- **Step structure**: Each step has `log_step "description"` followed by operations, ends with `}`
- **Version check**: `step_pipewire()` at line 383, returns 0 if PipeWire >= 1.4.11 already installed
- **Install flow**: Deps → Clone → Meson setup → Build → Install → ldconfig → Services → Verification

### pipewire-cleanup.sh Key Features (to integrate)
1. **Package detection**: dpkg-query for pipewire*, libpipewire-*, libspa-*, wireplumber*, libwireplower-, gstreamer1.0-pipewire
2. **APT purge simulation**: `apt-get -s purge` before actual removal
3. **User service check**: `systemctl --user cat` for pipewire, wireplumber services
4. **Config backup**: tar backup of /etc/pipewire, /etc/wireplumber, user configs, ALSA configs
5. **Manifest-based source removal**: Only remove files listed in root-owned manifest
6. **Dry-run/execute**: `--dry-run` vs `--execute`
7. **Explicit confirmation**: `read -r -p "PURGE"` before APT purge
8. **Service stoppage**: `systemctl --user stop` before removal
9. **Post-cleanup verification**: Check remaining binaries

## Integration Design

### New Step: `step_pipewire_cleanup()`
Added after `step_pipewire()` in the step sequence. Optional - can be triggered by:
- A `CLEANUP` installation mode option
- A post-installation flag
- Always runs after build (with appropriate guard conditions)

### Manifest Concept
The installer will write a manifest after source installation:
- Location: `$ACTUAL_HOME/.pipewire/manifest.txt` (root-owned, but read by cleanup)
- Format: One file path per line, absolute paths under allowed prefixes (`/usr/*`, `/usr/local/*`, `/opt/*`)
- Created by: `run_as_user` during build/install, tracked as root-owned
- Used by: `step_pipewire_cleanup()` to know exactly which source files to remove

### Flow

```
step_pipewire() [build/install] -->
  └── writes manifest at end of successful build
step_pipewire_cleanup() [new] -->
  ├── Detect distro packages via dpkg-query
  ├── Backup configurations
  ├── Check APT dependency impact (simulate purge)
  ├── Get explicit user confirmation
  ├── Stop user systemd services
  ├── Remove source files per manifest (dpkg-check first)
  ├── APT purge of distro packages (if confirmed)
  ├── Optional config purge
  ├── Verify cleanup (check for remaining files)
  └── Report
```

### Safety Rules (integrated)
- Never `rm` package-managed files (check dpkg-query first)
- No blanket `/usr/lib`, `/usr/share`, `/usr/bin`, `/etc` deletion
- Only remove files with verifiable root ownership (manifest)
- APT simulation before any purge
- User confirmation required before destructive actions
- Unknown legacy installs: inventory, don't guess
- Don't assume fixed prefix (respect `/usr/local`, `/usr`, etc.)

### Test Cases (to be created separately)
1. Fresh Ubuntu without PipeWire
2. Normal Ubuntu distro installation
3. PipeWire from Git with `/usr/local` prefix
4. PipeWire from Git with `/usr` prefix
5. Distro install overridden by source build
6. Source build without build directory
7. Source build without manifest
8. Existing WirePlumber Lua configs
9. Multiple found installation versions
10. User abort during cleanup

## Integration Details

### 1. Manifest Writing (in `step_pipewire()`)
After successful source install, write manifest:
```bash
# After ninja -C build install
mkdir -p "$ACTUAL_HOME/.pipewire"
run_as_user "find /usr/local -type f -o -type l > \"$ACTUAL_HOME/.pipewire/manifest.txt\" 2>/dev/null"
# Make root-owned
run_cmd_sudo "chown root:root \"$ACTUAL_HOME/.pipewire/manifest.txt\""
run_cmd_sudo "chmod 0600 \"$ACTUAL_HOME/.pipewire/manifest.txt\""
```

### 2. New Step Function
```bash
step_pipewire_cleanup() {
    log_step "PipeWire Cleanup"
    
    # 1. Detect distro packages
    # 2. Backup configs
    # 3. APT dependency simulation
    # 4. User confirmation
    # 5. Stop services
    # 6. Remove source files per manifest
    # 7. APT purge (if confirmed)
    # 8. Optional config purge
    # 9. Verify cleanup
}
```

### 3. Reusing Existing Helpers
- `run_as_user()` for user-context operations
- `run_cmd_sudo()` for root operations
- `prompt_yes_no()` for confirmation (already has TEST_MODE)
- `log_step()`, `log_info()`, etc. for logging
- `TEST_MODE` for dry-run mode
- Existing version check can guard the cleanup (only if PipeWire was installed by this installer)

### 4. Place in Step Sequence
After the existing `step_pipewire()` block (after the closing `}` at line ~486), add:
```bash
# New step - optionally run
if [ "$CLEANUP" = true ]; then
    step_pipewire_cleanup
fi
```

Or make it always-run but guard with "if PipeWire was installed by this installer".

## Implementation Priority
1. Add manifest writing to `step_pipewire()` after successful source install
2. Add `step_pipewire_cleanup()` function
3. Integrate cleanup into step sequence (conditional)
4. Create test cases

Let me now implement this step by step.