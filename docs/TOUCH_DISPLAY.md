# Touch Display

## Zielbild

- 800x480 als Basis
- große Buttons
- Tap statt Mausgefühl
- Cursor versteckt
- keine Desktop-Abhängigkeit

## Diagnose

```bash
hyrovi-panel touch-test
hyrovi-panel display-test
```

## Boot-Config

Das Setup prüft auf:

- `/boot/firmware/config.txt`
- `/boot/config.txt`
- `/boot/firmware/cmdline.txt`
- `/boot/cmdline.txt`

Wenn eine der Dateien existiert, wird ein Backup erstellt und ein Hyrovi-Block ergänzt.
Wenn eine `cmdline.txt` existiert, wird zusätzlich `consoleblank=0` angehängt.

## Gesten

Die App behandelt:

- Tap
- horizontale Swipes
- einfache vertikale Gesten

## Cursor

Die App blendet den Mauszeiger aus, wenn `ui.hide_cursor` aktiviert ist.
