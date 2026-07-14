# Setup Device

Voraussetzung ist ein frischer Raspberry Pi mit Raspberry Pi OS Lite.

## Installieren

```bash
git clone https://github.com/H-Y-R-O-V-I/hyrovi-touch-panel.git
cd hyrovi-touch-panel
sudo ./scripts/setup_device.sh
```

Das Setup:

- installiert Abhängigkeiten
- legt den Linux-User `hyrovi-panel` an
- erstellt `/opt/hyrovi-touch-panel`
- kopiert den aktuellen Repo-Stand als erstes Release
- schreibt die lokale Config nach `/etc/hyrovi-touch-panel/config.yaml`, falls sie noch fehlt
- aktiviert die systemd-Services

## Danach prüfen

```bash
hyrovi-panel status
hyrovi-panel doctor
hyrovi-panel logs
```

## Display-Setup

Das Setup passt die Boot-Config für HDMI an, wenn `/boot/firmware/config.txt` oder `/boot/config.txt` vorhanden ist.

Vorher wird immer ein Backup mit dem Suffix `.bak.hyrovi-<timestamp>` erstellt.
