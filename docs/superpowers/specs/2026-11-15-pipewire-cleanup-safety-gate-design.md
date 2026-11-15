# PipeWire-Cleanup: Schutzgate für APT-Purge + freiwilliger Rebuild

**Datum:** 2026-11-15
**Status:** Im Gespräch freigegeben (User: „perfekt! so umsetzen")

## Intent & Warum

Auf einem aktiven Linux-Mint/Cinnamon-System hat die PURGE-Simulation gezeigt,
dass das Entfernen der PipeWire-Distro-Pakete per Kaskade die Desktop-DE
zerstören würde (`cinnamon*`, `mint-meta-*`, `blueman`, `xdg-desktop-portal*`,
sogar `cable` aus diesem Projekt) und `pulseaudio` neu installiert. Der
PURGE-Prompt fing das zwar ab, aber das Erkennen gefährlicher Kaskaden darf
nicht vom Benutzer abhängen. Zusätzlich soll die Versionsprüfung keine harte
Grenze mehr sein: Auch bei erfüilter Untergrenze (≥ 1.4.11) soll der User die
Neueste-Version weiterhin selbst installieren können.

## Goals

1. **Schutzgate:** Die APT-Purge-Simulation wird automatisch ausgewertet.
   Verlässt die vollständige Entfernungskaskade (oder eine Neuinstallation)
   die PipeWire-Familien, wird der Distro-Purge komplett übersprungen —
   ohne Rückfrage, ohne Force-Override.
2. **Freifrage bei bestandener Versionsprüfung:** `prompt_yes_no` mit
   Default `n`; `ja` führt in denselben Cleanup+Build-Pfad wie „zu alt".

## Non-goals / Anti-goals

- Kein Force-/Override-Argument für das Gate (wer es erzwingen will, purget
  manuell per apt).
- Kein Trimmen der Purge-Liste (geht nicht: apt kaskadiert bei
  Kern-Bibliotheken immer).
- Kein zweiter, abweichender Codepfad für den Rebuild bei bestandener Prüfung.
- Keine Änderung an `TEST_MODE`-Semantik (Defaults werden auto-gewählt).

## Constraints (projektweit)

- Whitelist der erlaubten Familien (identisch zur Paketerkennung):
  `^pipewire($|-)`, `^libpipewire-`, `^libspa-`, `^wireplumber($|-)`,
  `^libwireplumber-`, exakt `gstreamer1.0-pipewire`.
- Simulationsausgabe mit `LC_ALL=C` erzwingen (Deutsche apt-Header sind
  nicht parsebar).
- Purge-Verhalten: Gate-Sauber → heutiges Verhalten (PURGE-Prompt,
  exakte Prompt-Zeile „Zum Fortfahren exakt PURGE eingeben" bleibt).
  Gate-Violation oder Simulationsfehler → kein Purge, Cleanup fährt mit
  Manifest/Config fort.
- `set -euo pipefail` ist aktiv: Simulations-Capture darf bei apt-Fehler
  nicht abbrechen.
- Sicherheitsregeln aus Runde 1 bleiben unberührt: kein `rm` paketverwalteter
  Dateien, kein `ninja uninstall`, Manifest nur root-eigen, PURGE vor jeder
  Entfernung, keine Löschung bei unklarem Eigentümer.

## Ansätze (diskutiert)

| # | Ansatz | Entscheidung |
|---|--------|--------------|
| A | Simulation-Schutzgate mit Whitelist; bei Kaskade automatisch Skip, Distro-Pakete bleiben, `/usr/local`-Build hat Vorrang | **gewählt** |
| B | Distro-Pakete grundsätzlich nie purgen | verworfen, aber als automatischer Fallback in A enthalten |
| C | Interaktive Auswahl/Force mit Schutzliste | verworfen (Footgun-Potenzial) |

## Entscheidungen (vom User bestätigt)

- **D1:** Gate-Regel = „Verletzung, wenn REMOVED-Kaskade auch nur ein Paket
  außerhalb der Whitelist enthält ODER die Simulation Neuinstallationen
  zeigt" (z. B. `pulseaudio`).
- **D2:** Bei Verletzung: Purge komplett überspringen, informativ loggen
  (welche Pakete, warum, `/usr/local`-Vorrang), Rest-Cleanup läuft weiter.
- **D3:** Rebuild-Prompt-Text: `Build and install the latest PipeWire version anyway?`
  mit Default `"n"`; Ablehnen = `return 0` (Zustand unverändert), Zustimmen =
  Fallthrough in den gemeinsamen Cleanup+Build-Pfad.
- **D4:** Kein Force-Override für das Gate.

## Offenes für den Builder

Keine — alle Schnittstellen, Strings und Tests sind im zugehörigen Plan
festgelegt (`docs/superpowers/plans/2026-11-15-pipewire-cleanup-safety-gate.md`).
