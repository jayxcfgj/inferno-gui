#!/usr/bin/env bash
#
# pipewire-cleanup.sh
#
# Ubuntu / Debian cleanup helper for an exclusive, source-built PipeWire stack.
# Safe by default: without --execute, this script only reports/simulates.
#
# IMPORTANT:
# - Distro packages are removed through APT, never by deleting their files.
# - Source files are removed ONLY when listed in a root-owned manifest created
#   by your own installer. Unknown legacy source installs are reported, not
#   guessed at or deleted.
# - User/system configuration is backed up and preserved by default.
#
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_NAME=${0##*/}
EXECUTE=0
KEEP_CONFIG=1
MANIFEST="/var/lib/your-installer/pipewire/manifest.txt"
BACKUP_ROOT="/var/backups/pipewire-cleanup"

log()  { printf '[%s] %s\n' "$SCRIPT_NAME" "$*"; }
warn() { printf '[%s] WARNUNG: %s\n' "$SCRIPT_NAME" "$*" >&2; }
die()  { printf '[%s] FEHLER: %s\n' "$SCRIPT_NAME" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Verwendung:
  $SCRIPT_NAME [--dry-run] [--execute] [--manifest DATEI] [--purge-config]

Optionen:
  --dry-run       Nur anzeigen/simulieren (Standard).
  --execute       Änderungen durchführen; vor APT-Purge ist eine Bestätigung nötig.
  --manifest      Root-eigenes Manifest der durch deinen Installer installierten
                  Dateien (Standard: $MANIFEST).
  --purge-config  Nach Backup auch bekannte System-/Benutzerkonfigurationen
                  entfernen. Standardmäßig bleiben sie erhalten.
  -h, --help      Diese Hilfe anzeigen.

Das Skript ist für Ubuntu/Debian mit dpkg und APT vorgesehen.
EOF
}

while (($#)); do
    case "$1" in
        --dry-run) EXECUTE=0 ;;
        --execute) EXECUTE=1 ;;
        --manifest)
            (($# >= 2)) || die "--manifest benötigt einen Dateipfad."
            MANIFEST=$2
            shift
            ;;
        --purge-config) KEEP_CONFIG=0 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1 (siehe --help)" ;;
    esac
    shift
done

[[ -r /etc/os-release ]] || die "/etc/os-release nicht gefunden."
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" || " ${ID_LIKE:-} " == *"debian"* ]] ||
    die "Dieses Skript unterstützt nur Ubuntu/Debian-artige Systeme."
command -v dpkg-query >/dev/null || die "dpkg-query fehlt."
command -v apt-get >/dev/null || die "apt-get fehlt."

[[ "$EUID" -ne 0 ]] || die "Bitte als normaler Desktop-Benutzer starten, nicht mit sudo. Das Skript verwendet sudo nur für Systemänderungen, damit systemctl --user die richtige Sitzung erreicht."

if (( EXECUTE )); then
    command -v sudo >/dev/null || die "sudo fehlt."
    sudo -v
    log "Ausführungsmodus aktiv."
else
    log "DRY-RUN: Es werden keine Änderungen vorgenommen. Für Änderungen --execute verwenden."
fi

run_root() {
    if (( EXECUTE )); then
        sudo "$@"
    else
        printf '  DRY-RUN: sudo'
        printf ' %q' "$@"
        printf '\n'
    fi
}

# Print installed packages in relevant package families. Deliberately excludes
# similarly named packages such as libspandsp.
mapfile -t PKGS < <(
    dpkg-query -W -f='${binary:Package}\t${db:Status-Status}\n' 2>/dev/null |
    awk -F '\t' '
      $2 == "installed" &&
      (
        $1 ~ /^pipewire($|-)/ ||
        $1 ~ /^libpipewire-/ ||
        $1 ~ /^libspa-/ ||
        $1 ~ /^wireplumber($|-)/ ||
        $1 ~ /^libwireplumber-/ ||
        $1 == "gstreamer1.0-pipewire"
      ) { print $1 }
    ' | sort -u
)

log "Erkannte Distro-Pakete:"
if ((${#PKGS[@]})); then
    printf '  %s\n' "${PKGS[@]}"
else
    log "Keine passenden installierten Pakete gefunden."
fi

# Report services. User services are stopped in the current user's session;
# running this script under sudo is intentionally not supported.
USER_UNITS=(
    pipewire.service pipewire.socket
    pipewire-pulse.service pipewire-pulse.socket
    wireplumber.service pipewire-media-session.service
)
log "User-Dienste, die angehalten werden:"
for unit in "${USER_UNITS[@]}"; do
    if systemctl --user cat "$unit" >/dev/null 2>&1; then
        log "  $unit"
    fi
done

# Backup system and current-user configuration before any destructive action.
timestamp=$(date +%Y%m%d-%H%M%S)
backup_dir="$BACKUP_ROOT/$timestamp"

backup_paths=()
for p in \
    /etc/pipewire /etc/wireplumber \
    /etc/alsa/conf.d/50-pipewire.conf \
    /etc/alsa/conf.d/99-pipewire-default.conf \
    /etc/security/limits.d/25-pw-rlimits.conf \
    "$HOME/.config/pipewire" "$HOME/.config/wireplumber" \
    "$HOME/.config/systemd/user/pipewire.service.d" \
    "$HOME/.config/systemd/user/pipewire-pulse.service.d" \
    "$HOME/.config/systemd/user/wireplumber.service.d"
do
    [[ -e "$p" || -L "$p" ]] && backup_paths+=("$p")
done

if ((${#backup_paths[@]})); then
    log "Konfigurations-Backup nach $backup_dir"
    if (( EXECUTE )); then
        sudo install -d -m 0700 "$backup_dir"
        # tar keeps absolute path structure below the archive root.
        sudo tar -czpf "$backup_dir/configuration.tar.gz" \
            --absolute-names "${backup_paths[@]}"
        sudo chmod 0600 "$backup_dir/configuration.tar.gz"
    else
        printf '  Würde sichern:\n'
        printf '    %s\n' "${backup_paths[@]}"
    fi
else
    log "Keine bekannten Konfigurationsverzeichnisse/-dateien zum Sichern gefunden."
fi

# Simulate the package transaction and, in execute mode, obtain confirmation
# BEFORE stopping services or removing any source-installed files.
if ((${#PKGS[@]})); then
    log "APT-Purge-Simulation (bitte die Liste der zu entfernenden Pakete prüfen):"
    apt-get -s purge --no-auto-remove "${PKGS[@]}" ||
        die "APT-Simulation fehlgeschlagen. Es wurde nichts entfernt."

    if (( EXECUTE )); then
        printf '\nAPT wird die oben angezeigten Pakete/Abhängigkeiten entfernen.\n'
        printf 'Wenn dabei Desktop-, Audio-, Bluetooth- oder andere benötigte Pakete betroffen sind: ABBRECHEN.\n'
        read -r -p "Zum Fortfahren exakt PURGE eingeben: " answer
        [[ "$answer" == "PURGE" ]] || die "Vom Benutzer abgebrochen."
        for unit in "${USER_UNITS[@]}"; do
            systemctl --user stop "$unit" >/dev/null 2>&1 || true
        done
    fi
fi

# Remove only exact files listed by the installer's root-owned manifest.
# Never call ninja uninstall automatically: it does not check dpkg ownership.
if [[ -e "$MANIFEST" ]]; then
    owner=$(stat -c '%u' "$MANIFEST" 2>/dev/null || printf 'unknown')
    [[ "$owner" == "0" ]] || die "Manifest ist nicht root-eigen: $MANIFEST"
    log "Prüfe Source-Installationsmanifest: $MANIFEST"

    while IFS= read -r path || [[ -n "$path" ]]; do
        [[ -z "$path" || "$path" == \#* ]] && continue
        [[ "$path" == /* ]] || { warn "Relativer Manifestpfad übersprungen: $path"; continue; }
        [[ "$path" != "/" ]] || { warn "Root-Pfad im Manifest übersprungen."; continue; }
        case "$path" in
            /usr/*|/usr/local/*|/opt/*) ;;
            *) warn "Pfad außerhalb erlaubter Prefixe übersprungen: $path"; continue ;;
        esac

        # Directories are never removed from the manifest.
        if [[ -d "$path" && ! -L "$path" ]]; then
            warn "Verzeichnis wird nicht entfernt: $path"
            continue
        fi
        if ! [[ -e "$path" || -L "$path" ]]; then
            continue
        fi

        # If dpkg owns the path, leave it to APT even if an old source build
        # overwrote its contents. This prevents the failure seen with /usr.
        if dpkg-query -S "$path" >/dev/null 2>&1; then
            warn "Von dpkg verwaltet, bleibt erhalten: $path"
            continue
        fi

        log "Source-Datei entfernen: $path"
        run_root rm -f -- "$path"
    done < "$MANIFEST"

    log "Manifest-Datei bleibt zur Nachvollziehbarkeit erhalten: $MANIFEST"
else
    warn "Kein eigenes Installationsmanifest gefunden: $MANIFEST"
    warn "Unbekannte/frühere Source-Installationen werden NICHT automatisch gelöscht."
    warn "Für Altinstallationen zuerst Build-Verzeichnis/Prefix ermitteln und Dateien inventarisieren."
fi

# The APT transaction was simulated and (in execute mode) explicitly approved
# above. Perform the package removal only after source-manifest handling.
if ((${#PKGS[@]})); then
    if (( EXECUTE )); then
        sudo apt-get purge --no-auto-remove -y "${PKGS[@]}"
    else
        log "Distro-Pakete würden mit APT entfernt; Dry-Run aktiv."
    fi
else
    log "APT-Purge übersprungen: keine passenden Pakete installiert."
fi

# Optional configuration removal, only after backup. Keep user customizations
# by default. Do not touch /usr/share content manually; package manager owns it.
if (( ! KEEP_CONFIG )); then
    log "Konfigurations-Reset ausgewählt."
    config_paths=(
        /etc/pipewire /etc/wireplumber
        /etc/alsa/conf.d/50-pipewire.conf
        /etc/alsa/conf.d/99-pipewire-default.conf
        /etc/security/limits.d/25-pw-rlimits.conf
        "$HOME/.config/pipewire" "$HOME/.config/wireplumber"
        "$HOME/.config/systemd/user/pipewire.service.d"
        "$HOME/.config/systemd/user/pipewire-pulse.service.d"
        "$HOME/.config/systemd/user/wireplumber.service.d"
    )
    for p in "${config_paths[@]}"; do
        [[ -e "$p" || -L "$p" ]] || continue
        # Never remove a path still owned by a package.
        if dpkg-query -S "$p" >/dev/null 2>&1; then
            warn "Paketverwaltete Konfiguration bleibt erhalten: $p"
            continue
        fi
        log "Konfiguration entfernen: $p"
        run_root rm -rf -- "$p"
    done
else
    log "Konfigurationen bleiben erhalten (Standardverhalten). Backup wurde erstellt, sofern Dateien existierten."
fi

if (( EXECUTE )); then
    sudo ldconfig
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

log "Abschlussprüfung:"
for cmd in pipewire pipewire-pulse wireplumber wpctl; do
    if command -v "$cmd" >/dev/null 2>&1; then
        log "  Noch im PATH: $cmd -> $(command -v "$cmd")"
    else
        log "  Nicht im PATH: $cmd"
    fi
done

if (( EXECUTE )); then
    log "Bereinigung abgeschlossen. Starte jetzt noch KEINE neue Installation, bevor die Abschlussprüfung ausgewertet wurde."
else
    log "Dry-Run abgeschlossen. Für tatsächliche Änderungen erneut mit --execute starten."
fi
