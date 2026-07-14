# Config

Die produktive Konfiguration liegt unter:

```text
/etc/hyrovi-touch-panel/config.yaml
```

Die Vorlage liegt im Repo als:

```text
config.example.yaml
```

## Beispiel

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: ""

ui:
  fullscreen: true
  screen_width: 800
  screen_height: 480
  hide_cursor: true
  refresh_interval: 1.0

touch:
  mode: "pygame"
  enable_gestures: true

updates:
  enabled: true
  github_repo: "H-Y-R-O-V-I/hyrovi-touch-panel"
  channel: "stable"
  check_on_boot: true
  boot_delay_seconds: 60
  auto_update: true
  rollback_on_failed_healthcheck: true

entities:
  main_light: "light.extended_color_light_3"
  temperature: "sensor.wohnzimmer_temperatur"
  humidity: "sensor.wohnzimmer_luftfeuchtigkeit"
```

## Hinweise

- Keine Secrets ins Repo.
- Token nur lokal in `/etc/hyrovi-touch-panel/config.yaml`.
- Wenn Home Assistant noch nicht konfiguriert ist, läuft die App im Mock-Modus.
