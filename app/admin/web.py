from __future__ import annotations

import base64
import html
import json
import subprocess
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, render_template_string, request, url_for

from app.config.loader import (
    AppConfig,
    HomeAssistantUrlError,
    dump_config_data,
    load_config,
    normalize_home_assistant_url,
    read_config_data,
)
from app.doctor import run_doctor
from app.ha.client import HomeAssistantClient
from app.runtime import CONFIG_FILE, CURRENT_LINK, PREVIOUS_LINK, current_release_dir, read_release_metadata
from app.update import UpdateError, list_installed_releases, rollback_release, update_release

CONFIG_SAVE_HELPER = "/usr/local/bin/hyrovi-touch-config-save"


def _systemctl_status(service: str) -> str:
    proc = subprocess.run(["systemctl", "is-active", service], text=True, capture_output=True)
    return proc.stdout.strip() or proc.stderr.strip() or "unknown"


def _tail_logs(service: str, lines: int = 120) -> str:
    proc = subprocess.run([
        "journalctl",
        "-u",
        service,
        "-n",
        str(lines),
        "--no-pager",
    ], text=True, capture_output=True, check=False)
    return proc.stdout.strip() or proc.stderr.strip() or "No logs available."


def _service_action(action: str, service: str) -> None:
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", action, service], check=False)


def _basic_auth_required(config: AppConfig) -> bool:
    return bool(config.admin.pin.strip())


def _auth_ok(config: AppConfig) -> bool:
    if not _basic_auth_required(config):
        return True
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
    except Exception:
        return False
    _, _, password = decoded.partition(":")
    return password == config.admin.pin


def _auth_challenge() -> Response:
    return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Hyrovi Touch Admin"'})


def _release_info() -> dict[str, Any]:
    current = current_release_dir()
    metadata = read_release_metadata(current) if current else None
    return {
        "current": str(current) if current else "unknown",
        "version": metadata.version if metadata else "unknown",
        "ref": metadata.ref if metadata else "unknown",
        "channel": metadata.channel if metadata else "unknown",
        "sha": metadata.git_sha if metadata else "unknown",
        "previous": str(PREVIOUS_LINK.resolve(strict=False)) if PREVIOUS_LINK.exists() or PREVIOUS_LINK.is_symlink() else "unknown",
    }


def _ha_client(config: AppConfig) -> HomeAssistantClient:
    return HomeAssistantClient.from_config(config)


def _entity_rows(client: HomeAssistantClient) -> list[dict[str, str]]:
    result = client.list_states()
    rows: list[dict[str, str]] = []
    if not result.ok or not isinstance(result.data, list):
        return rows
    for entity in result.data:
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("entity_id", ""))
        attributes = entity.get("attributes", {}) if isinstance(entity.get("attributes"), dict) else {}
        friendly_name = str(attributes.get("friendly_name", "")) if isinstance(attributes, dict) else ""
        rows.append(
            {
                "entity_id": entity_id,
                "friendly_name": friendly_name,
                "domain": entity_id.split(".", 1)[0] if "." in entity_id else "",
                "state": str(entity.get("state", "")),
            }
        )
    return rows


def _json_response(data: dict[str, Any], status: int = 200) -> Response:
    return Response(json.dumps(data, ensure_ascii=False, indent=2), status=status, mimetype="application/json")


def _config_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "home_assistant": {
            "url": config.home_assistant.url,
            "token_present": bool(config.home_assistant.token.strip()),
        },
        "entities": {
            "main_light": config.entities.main_light,
            "temperature": config.entities.temperature,
            "humidity": config.entities.humidity,
        },
        "ui": {
            "fullscreen": config.ui.fullscreen,
            "screen_width": config.ui.screen_width,
            "screen_height": config.ui.screen_height,
            "refresh_interval": config.ui.refresh_interval,
        },
    }


def _save_config_data(data: dict[str, Any]) -> tuple[bool, str]:
    payload = dump_config_data(data)
    proc = subprocess.run(
        ["sudo", "-n", CONFIG_SAVE_HELPER, str(CONFIG_FILE)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Failed to save configuration.").strip()
        return False, detail
    return True, "Configuration saved atomically."


def _merge_home_assistant_config(current: dict[str, Any], form: dict[str, str], *, delete_token: bool = False) -> tuple[bool, str, dict[str, Any]]:
    merged = dict(current)
    home_assistant = merged.get("home_assistant", {})
    if not isinstance(home_assistant, dict):
        home_assistant = {}
    else:
        home_assistant = dict(home_assistant)

    raw_url = form.get("url", "").strip() or str(home_assistant.get("url", "")).strip()
    try:
        if raw_url:
            home_assistant["url"] = normalize_home_assistant_url(raw_url)
        else:
            return False, "Home Assistant URL must not be empty.", merged
    except HomeAssistantUrlError as exc:
        return False, f"Invalid Home Assistant URL: {exc}", merged

    current_token = str(home_assistant.get("token", ""))
    if delete_token:
        home_assistant["token"] = ""
    else:
        new_token = form.get("token", "")
        home_assistant["token"] = new_token if new_token.strip() else current_token

    merged["home_assistant"] = home_assistant

    entities = merged.get("entities", {})
    if not isinstance(entities, dict):
        entities = {}
    else:
        entities = dict(entities)
    for key in ("main_light", "temperature", "humidity"):
        value = form.get(key, "").strip()
        if value:
            entities[key] = value
    merged["entities"] = entities
    return True, "Configuration updated.", merged


def _render_index(config: AppConfig, message: str = "") -> str:
    report = run_doctor(config.source_path or CONFIG_FILE)
    releases = list_installed_releases()
    info = _release_info()
    services = {
        "panel": _systemctl_status("hyrovi-touch-panel.service"),
        "admin": _systemctl_status("hyrovi-touch-admin.service"),
        "update": _systemctl_status("hyrovi-touch-update-on-boot.service"),
    }
    ha = _ha_client(config).healthcheck()
    ha_connected = ha.ok and ha.source == "ha"
    template = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Hyrovi Touch Admin</title>
      <style>
        :root { color-scheme: dark; --bg:#0f1318; --panel:#18212b; --panel2:#202b36; --text:#eef3f7; --muted:#9fb0bf; --ok:#4dd48a; --bad:#ff7b7b; --accent:#59a4ff; }
        body { margin:0; font-family: system-ui, sans-serif; background: radial-gradient(circle at top, #18212b, #0f1318 60%); color: var(--text); }
        .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
        .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; }
        .card { background: rgba(24,33,43,.94); border:1px solid #273340; border-radius:18px; padding:18px; box-shadow:0 20px 50px rgba(0,0,0,.25); }
        h1,h2 { margin:0 0 12px 0; }
        .muted { color: var(--muted); }
        .ok { color: var(--ok); }
        .bad { color: var(--bad); }
        .btn { display:inline-block; margin:4px 6px 0 0; padding:12px 16px; border-radius:14px; background: var(--panel2); color: var(--text); text-decoration:none; border:1px solid #324354; }
        .btn.primary { background: linear-gradient(135deg, #2e7dff, #64b5ff); color:#06111f; font-weight:700; }
        pre { white-space: pre-wrap; word-break: break-word; background:#0d1116; padding:14px; border-radius:14px; overflow:auto; }
        table { width:100%; border-collapse: collapse; }
        td, th { text-align:left; padding:8px 4px; border-bottom:1px solid #273340; }
      </style>
    </head>
    <body>
    <div class="wrap">
      <h1>Hyrovi Touch Admin</h1>
      <p class="muted">Lokale Recovery- und Diagnoseoberfläche auf Port 8765.</p>
      {% if message %}<div class="card" style="border-color: #43627e; margin-bottom:16px;">{{ message }}</div>{% endif %}
      <div class="grid">
        <div class="card">
          <h2>Status</h2>
          <div class="{{ 'ok' if report.ok else 'bad' }}">{{ 'Gesund' if report.ok else 'Prüfung fehlgeschlagen' }}</div>
          <p class="muted">Systemd: Panel={{ services.panel }}, Admin={{ services.admin }}, Update={{ services.update }}</p>
          <p class="muted">Home Assistant: {{ 'Verbunden' if ha_connected else 'Offline' }}</p>
        </div>
        <div class="card">
          <h2>Version</h2>
          <div>{{ info.version }}</div>
          <p class="muted">Ref: {{ info.ref }}</p>
          <p class="muted">SHA: {{ info.sha }}</p>
        </div>
        <div class="card">
          <h2>Aktionen</h2>
          <a class="btn primary" href="{{ url_for('update_now') }}">Update jetzt</a>
          <a class="btn" href="{{ url_for('rollback_now') }}">Rollback</a>
          <a class="btn" href="{{ url_for('restart_services') }}">Services neu starten</a>
          <a class="btn" href="{{ url_for('healthcheck') }}">Healthcheck</a>
        </div>
        <div class="card">
          <h2>Home Assistant</h2>
          <p class="muted">URL: {{ config.home_assistant.url }}</p>
          <p class="muted">Token vorhanden: {{ 'Ja' if config.home_assistant.token.strip() else 'Nein' }}</p>
          <a class="btn primary" href="{{ url_for('home_assistant_page') }}">Öffnen</a>
        </div>
        <div class="card">
          <h2>Service Steuerung</h2>
          <a class="btn" href="{{ url_for('service_action', action='start', service='hyrovi-touch-panel.service') }}">Panel Start</a>
          <a class="btn" href="{{ url_for('service_action', action='stop', service='hyrovi-touch-panel.service') }}">Panel Stop</a>
          <a class="btn" href="{{ url_for('service_action', action='restart', service='hyrovi-touch-panel.service') }}">Panel Restart</a>
          <a class="btn" href="{{ url_for('service_action', action='start', service='hyrovi-touch-admin.service') }}">Admin Start</a>
          <a class="btn" href="{{ url_for('service_action', action='stop', service='hyrovi-touch-admin.service') }}">Admin Stop</a>
          <a class="btn" href="{{ url_for('service_action', action='restart', service='hyrovi-touch-admin.service') }}">Admin Restart</a>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="card">
          <h2>Releases</h2>
          <table>
            <tr><th>Name</th><th>Version</th><th>Aktiv</th></tr>
            {% for release in releases %}
              <tr><td>{{ release.name }}</td><td>{{ release.version }}</td><td>{{ release.current }}</td></tr>
            {% endfor %}
          </table>
        </div>
        <div class="card">
          <h2>Checks</h2>
          <pre>{{ checks }}</pre>
        </div>
      </div>
      <div class="grid" style="margin-top:16px;">
        <div class="card">
          <h2>Logs</h2>
          <a class="btn" href="{{ url_for('logs') }}">Panel Logs</a>
          <a class="btn" href="{{ url_for('display_test') }}">Display-Test</a>
          <a class="btn" href="{{ url_for('touch_test') }}">Touch-Test</a>
        </div>
      </div>
    </div>
    </body>
    </html>
    """
    return render_template_string(
        template,
        report=report,
        releases=releases,
        info=info,
        services=services,
        checks=report.format_text(),
        config=config,
        message=message,
        ha_connected=ha_connected,
    )


def _render_home_assistant(config: AppConfig, message: str = "", error: str = "") -> str:
    client = _ha_client(config)
    entity_rows = _entity_rows(client)
    status = client.healthcheck()
    api_status = client.list_states()
    template = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Home Assistant - Hyrovi Touch Admin</title>
      <style>
        :root { color-scheme: dark; --bg:#0f1318; --panel:#18212b; --panel2:#202b36; --text:#eef3f7; --muted:#9fb0bf; --ok:#4dd48a; --bad:#ff7b7b; --accent:#59a4ff; }
        body { margin:0; font-family: system-ui, sans-serif; background: radial-gradient(circle at top, #18212b, #0f1318 60%); color: var(--text); }
        .wrap { max-width: 1300px; margin: 0 auto; padding: 24px; }
        .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; }
        .card { background: rgba(24,33,43,.94); border:1px solid #273340; border-radius:18px; padding:18px; box-shadow:0 20px 50px rgba(0,0,0,.25); }
        h1,h2 { margin:0 0 12px 0; }
        .muted { color: var(--muted); }
        .ok { color: var(--ok); }
        .bad { color: var(--bad); }
        .btn { display:inline-block; margin:4px 6px 0 0; padding:12px 16px; border-radius:14px; background: var(--panel2); color: var(--text); text-decoration:none; border:1px solid #324354; }
        .btn.primary { background: linear-gradient(135deg, #2e7dff, #64b5ff); color:#06111f; font-weight:700; }
        input, select { width:100%; box-sizing:border-box; background:#0d1116; color:var(--text); border:1px solid #324354; border-radius:12px; padding:10px 12px; margin:4px 0 12px; }
        label { display:block; margin-top:10px; font-weight:600; }
        table { width:100%; border-collapse: collapse; }
        th, td { text-align:left; padding:8px 6px; border-bottom:1px solid #273340; vertical-align:top; }
        .small { font-size: 0.9rem; }
      </style>
      <script>
        function filterEntities() {
          const query = document.getElementById('entity-filter').value.toLowerCase();
          document.querySelectorAll('[data-entity-row]').forEach((row) => {
            row.style.display = row.dataset.search.includes(query) ? '' : 'none';
          });
        }
      </script>
    </head>
    <body>
    <div class="wrap">
      <h1>Home Assistant</h1>
      <p class="muted">URL, Token und Entities werden hier verwaltet. Ein leeres Tokenfeld behält den bestehenden Token.</p>
      {% if message %}<div class="card" style="border-color:#43627e; margin-bottom:16px;">{{ message }}</div>{% endif %}
      {% if error %}<div class="card" style="border-color:#8b4a4a; margin-bottom:16px; color:var(--bad);">{{ error }}</div>{% endif %}
      <div class="grid">
        <div class="card">
          <h2>Konfiguration</h2>
          <form method="post" action="{{ url_for('home_assistant_save') }}">
            <label for="url">Home Assistant URL</label>
            <input id="url" name="url" value="{{ config.home_assistant.url }}" placeholder="http://homeassistant.local:8123">
            <label for="token">Neues Token</label>
            <input id="token" name="token" type="password" placeholder="Leer lassen, um das bestehende Token zu behalten">
            <label for="main_light">Main light</label>
            <input id="main_light" name="main_light" list="ha-entity-list" value="{{ config.entities.main_light }}">
            <label for="temperature">Temperature</label>
            <input id="temperature" name="temperature" list="ha-entity-list" value="{{ config.entities.temperature }}">
            <label for="humidity">Humidity</label>
            <input id="humidity" name="humidity" list="ha-entity-list" value="{{ config.entities.humidity }}">
            <div>
              <button class="btn primary" type="submit">Speichern</button>
              <a class="btn" href="{{ url_for('home_assistant_test') }}">Verbindung testen</a>
              <a class="btn" href="{{ url_for('index') }}">Zurück</a>
            </div>
          </form>
          <form method="post" action="{{ url_for('home_assistant_delete_token') }}" onsubmit="return confirm('Token wirklich löschen?');" style="margin-top:12px;">
            <button class="btn" type="submit">Token löschen</button>
          </form>
          <p class="muted" style="margin-top:12px;">Token vorhanden: {{ 'Ja' if config.home_assistant.token.strip() else 'Nein' }}</p>
          <p class="muted">Verbindung: <span class="{{ 'ok' if status.ok and status.source == 'ha' else 'bad' }}">{{ 'Verbunden' if status.ok and status.source == 'ha' else 'Offline' }}</span></p>
          <p class="muted">Status: {{ status.detail }}</p>
          <p class="muted">API: {{ api_status.detail }}</p>
          <div class="small">Aktuelle Entity-Auswahl wird direkt aus dem konfigurierten HA gelesen.</div>
        </div>
        <div class="card">
          <h2>Entities</h2>
          <label for="entity-filter">Suchen</label>
          <input id="entity-filter" oninput="filterEntities()" placeholder="entity_id, friendly name, domain oder state">
          <table>
            <thead>
              <tr><th>Entity-ID</th><th>Friendly Name</th><th>Domain</th><th>Zustand</th></tr>
            </thead>
            <tbody>
              {% for row in entity_rows %}
                <tr data-entity-row data-search="{{ (row.entity_id ~ ' ' ~ row.friendly_name ~ ' ' ~ row.domain ~ ' ' ~ row.state)|lower }}">
                  <td>{{ row.entity_id }}</td>
                  <td>{{ row.friendly_name }}</td>
                  <td>{{ row.domain }}</td>
                  <td>{{ row.state }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
          <datalist id="ha-entity-list">
            {% for row in entity_rows %}
              <option value="{{ row.entity_id }}">{{ row.friendly_name }} ({{ row.state }})</option>
            {% endfor %}
          </datalist>
        </div>
      </div>
    </div>
    </body>
    </html>
    """
    return render_template_string(
        template,
        config=config,
        entity_rows=entity_rows,
        status=status,
        api_status=api_status,
        message=message,
        error=error,
    )


def create_app(config_path: Path = CONFIG_FILE) -> Flask:
    app = Flask(__name__)
    app.config["HYROVI_CONFIG_PATH"] = config_path

    def current_config() -> AppConfig:
        return load_config(config_path)

    @app.before_request
    def _check_auth() -> Response | None:
        if not _auth_ok(current_config()):
            return _auth_challenge()
        return None

    @app.get("/")
    def index() -> str:
        return _render_index(current_config())

    @app.get("/healthcheck")
    def healthcheck() -> str:
        report = run_doctor(config_path)
        return "<pre>" + html.escape(report.format_text()) + "</pre>"

    @app.get("/logs")
    def logs() -> str:
        return "<pre>" + html.escape(_tail_logs("hyrovi-touch-panel.service")) + "</pre>"

    @app.get("/touch-test")
    def touch_test() -> str:
        return "<pre>Touch-Test laeuft ueber das CLI: hyrovi-panel touch-test</pre>"

    @app.get("/display-test")
    def display_test() -> str:
        return "<pre>Display-Test laeuft ueber das CLI: hyrovi-panel display-test</pre>"

    @app.get("/restart-services")
    def restart_services() -> Response:
        _service_action("restart", "hyrovi-touch-panel.service")
        _service_action("restart", "hyrovi-touch-admin.service")
        return redirect(url_for("index"))

    @app.get("/service/<action>/<path:service>")
    def service_action(action: str, service: str) -> Response:
        if action not in {"start", "stop", "restart"}:
            return Response("Unsupported action", 400)
        _service_action(action, service)
        return redirect(url_for("index"))

    @app.get("/update-now")
    def update_now() -> Response:
        try:
            update_release(load_config(config_path))
        except UpdateError as exc:
            return Response(f"Update failed: {exc}", 500)
        return redirect(url_for("index"))

    @app.get("/rollback-now")
    def rollback_now() -> Response:
        try:
            rollback_release(config_path)
        except UpdateError as exc:
            return Response(f"Rollback failed: {exc}", 500)
        return redirect(url_for("index"))

    @app.get("/home-assistant")
    def home_assistant_page() -> str:
        return _render_home_assistant(current_config())

    @app.post("/home-assistant/save")
    def home_assistant_save() -> str:
        config = current_config()
        raw = read_config_data(config_path)
        ok, detail, merged = _merge_home_assistant_config(raw, request.form)
        if not ok:
            return _render_home_assistant(config, error=detail)
        saved, save_detail = _save_config_data(merged)
        if not saved:
            return _render_home_assistant(config, error=save_detail)
        _service_action("restart", "hyrovi-touch-panel.service")
        return _render_home_assistant(load_config(config_path), message="Konfiguration gespeichert und Panel-Service neu gestartet.")

    @app.post("/home-assistant/delete-token")
    def home_assistant_delete_token() -> str:
        config = current_config()
        raw = read_config_data(config_path)
        ok, detail, merged = _merge_home_assistant_config(raw, {}, delete_token=True)
        if not ok:
            return _render_home_assistant(config, error=detail)
        saved, save_detail = _save_config_data(merged)
        if not saved:
            return _render_home_assistant(config, error=save_detail)
        _service_action("restart", "hyrovi-touch-panel.service")
        return _render_home_assistant(load_config(config_path), message="Token gelöscht und Panel-Service neu gestartet.")

    @app.route("/home-assistant/test", methods=["GET", "POST"])
    def home_assistant_test() -> str:
        config = current_config()
        client = _ha_client(config)
        health = client.healthcheck()
        parts = [f"API: {health.detail}"]
        if client.enabled and health.ok:
            for label, entity_id in (
                ("main_light", config.entities.main_light),
                ("temperature", config.entities.temperature),
                ("humidity", config.entities.humidity),
            ):
                result = client.get_state(entity_id)
                parts.append(f"{label}: {result.detail if not result.ok else result.data.get('state', 'unknown') if isinstance(result.data, dict) else 'ok'}")
        message = " | ".join(parts)
        return _render_home_assistant(config, message=message)

    @app.get("/api/home-assistant/status")
    def home_assistant_status_api() -> Response:
        config = current_config()
        client = _ha_client(config)
        result = client.healthcheck()
        return _json_response(
            {
                "ok": result.ok,
                "connected": bool(result.ok and result.source == "ha"),
                "url": config.home_assistant.url,
                "token_present": bool(config.home_assistant.token.strip()),
                "detail": result.detail,
            }
        )

    @app.get("/api/home-assistant/entities")
    def home_assistant_entities_api() -> Response:
        config = current_config()
        rows = _entity_rows(_ha_client(config))
        return _json_response({"ok": True, "entities": rows})

    return app


def main() -> int:
    app = create_app(CONFIG_FILE)
    app.run(host="0.0.0.0", port=8765, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
