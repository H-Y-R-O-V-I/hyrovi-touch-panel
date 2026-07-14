# Hyrovi Touch Panel

Lokale Touch-UI für Raspberry Pi OS Lite auf einem festen HDMI-/USB-Touchscreen.

Ziel:

- kein Chromium
- kein Desktop
- kein Home-Assistant-Webdashboard
- Python/Pygame als leichte lokale Bedienoberfläche
- Home Assistant später nur über die API

## Schnellstart auf dem Zielgerät

```bash
git clone https://github.com/H-Y-R-O-V-I/hyrovi-touch-panel.git
cd hyrovi-touch-panel
sudo ./scripts/setup_device.sh
```

Danach:

```bash
hyrovi-panel status
hyrovi-panel logs
hyrovi-panel update
hyrovi-panel rollback
```

## Projektstruktur

- `app/` Anwendungslogik
- `app/ui/` Pygame-UI und Diagnoseansichten
- `app/ha/` Home-Assistant-Client
- `app/config/` Config-Lader
- `admin/` Platz für lokale Admin-Artefakte
- `scripts/` Setup-, Diagnose- und CLI-Wrapper
- `systemd/` Service-Definitionen
- `docs/` Installations-, Update- und Recovery-Dokumente
- `assets/` Platz für Icons und Bilder

## Betrieb

- Die produktive Config liegt außerhalb des Repos unter `/etc/hyrovi-touch-panel/config.yaml`
- Die Release-Dateien liegen unter `/opt/hyrovi-touch-panel/releases/`
- Die aktive Version ist `/opt/hyrovi-touch-panel/current`
- Die frühere Version ist `/opt/hyrovi-touch-panel/previous`
- Die venv liegt unter `/opt/hyrovi-touch-panel/venv`

## Dienste

- `hyrovi-touch-panel.service` startet die Pygame-UI
- `hyrovi-touch-admin.service` startet die lokale Admin-Webseite auf Port `8765`
- `hyrovi-touch-update-on-boot.service` prüft nach dem Booten auf Updates

Die Admin-Webseite ist dann unter `http://<pi-ip>:8765` erreichbar.

## Entwicklung

```bash
./scripts/install_dev.sh
./scripts/check.sh
./scripts/run.sh
```

## Hinweise

- Keine Secrets ins Repo einchecken.
- `config.example.yaml` ist nur eine Vorlage.
- Update und Rollback laufen über Release-Ordner, nicht über ein blindes `git pull`.
