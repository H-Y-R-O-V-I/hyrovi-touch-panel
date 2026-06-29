# Hyrovi Touch Panel

Lokale, leichte Touch-UI für einen Raspberry Pi mit 5-Zoll-HDMI-/USB-Touchscreen.

## Projektziel

- Eigenes lokales Touch-Panel statt Home-Assistant-Webdashboard
- Sehr schlanke Oberfläche auf Basis von Python und `pygame`
- Spaterer Betrieb auf Raspberry Pi Zero oder Zero 2 W
- Home Assistant wird nur uber die API angesprochen, nicht uber Chromium oder ein Web-Frontend

## Warum kein HA-Webdashboard

- Kein Browser-Stack als Dauerlast
- Schnellere Startzeit und weniger RAM-Verbrauch
- Weniger Abhangigkeiten auf dem Zielsystem
- Bessere Kontrolle uber das Layout fur einen festen Touchscreen

## Zielplattform

- Entwicklung aktuell auf dem Raspberry Pi 5
- Ziel spater: Raspberry Pi Zero oder Zero 2 W
- 800x480 als Basislayout
- Skalierbar und fullscreen-fahig

## Projektstruktur

- `app/` Anwendungslogik
- `app/ui/` Mock-UI und Rendering
- `app/ha/` Home-Assistant-Platzhalter
- `app/config/` Config-Loader
- `assets/` Spatere Icons/Bilder
- `scripts/` Install-, Start- und Check-Skripte
- `systemd/` vorbereitete Service-Datei
- `docs/` Platz fur weitere Doku

## Installation auf Raspberry Pi OS Lite

1. Projekt nach `/home/carsten/programmieren/hyrovi-touch-panel` kopieren
2. Im Projektordner das Dev-Setup anlegen:

```bash
./scripts/install_dev.sh
```

3. Konfiguration anlegen:

```bash
cp config.example.yaml config.yaml
```

4. Mock-App starten:

```bash
./scripts/run.sh
```

Hinweis: Auf Pi Zero und Pi Zero 2 W kann fullscreen in `config.yaml` auf `true` gesetzt werden.

## Dev-Start auf dem Pi 5

```bash
./scripts/install_dev.sh
./scripts/check.sh
./scripts/run.sh
```

Die App lauft im Moment nur als lokale Mock-Oberflache. Es werden noch keine echten Home-Assistant-Services aufgerufen.

## Home Assistant Token Hinweise

- Kein Token in Git einchecken
- Das echte Token spater nur in `config.yaml` oder uber ein sicheres Secret-Handling ablegen
- `config.example.yaml` bleibt bewusst ohne Geheimnisse

## systemd Autostart

Die Datei `systemd/hyrovi-touch-panel.service` ist vorbereitet, aber nicht aktiviert.

Spatere Installation auf dem Zielsystem:

```bash
sudo cp systemd/hyrovi-touch-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hyrovi-touch-panel.service
sudo systemctl start hyrovi-touch-panel.service
```

Der Service startet dann `app.py` aus der venv.

## GitHub Push spaeter

Das Repository ist lokal initialisiert und kann spater nach `H-Y-R-O-V-I/hyrovi-touch-panel` gepusht werden:

```bash
git remote add origin git@github.com:H-Y-R-O-V-I/hyrovi-touch-panel.git
git branch -M main
git push -u origin main
```

## Naechste Schritte

- Echte Home-Assistant-API Anbindung
- Icons und Feinschliff fur die Touch-Navigation
- Mehrere Lichtszenen oder Raumseiten
- Autostart auf dem Ziel-Pi validieren

