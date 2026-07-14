# Recovery

## Admin-Webseite

Die Admin-Seite läuft getrennt von der Haupt-UI:

```bash
http://<pi-ip>:8765
```

Von dort sind möglich:

- Status ansehen
- Healthcheck starten
- Update starten
- Rollback starten
- Services neu starten
- Logs anzeigen

## CLI

```bash
hyrovi-panel status
hyrovi-panel doctor
hyrovi-panel logs
hyrovi-panel update
hyrovi-panel rollback
hyrovi-panel restart
```

## Wenn die UI kaputt ist

Die Admin-Webseite bleibt unabhängig von der Pygame-App startbar.
Wenn die Haupt-UI nicht sauber bootet, ist der erste Weg:

1. `hyrovi-panel doctor`
2. `hyrovi-panel logs`
3. `hyrovi-panel rollback`
