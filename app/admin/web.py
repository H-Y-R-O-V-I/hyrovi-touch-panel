from __future__ import annotations

import base64
import html
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
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
    proc = subprocess.run(
        ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout.strip() or proc.stderr.strip() or "No logs available."


def _restart_panel_service() -> None:
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "restart", "hyrovi-touch-panel.service"], check=False)


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
        "dashboard": {
            "pages": [
                {
                    "id": page.id,
                    "label": page.label,
                    "visible": page.visible,
                    "order": page.order,
                    "tiles": [
                        {
                            "id": tile.id,
                            "page": tile.page,
                            "type": tile.type,
                            "entity_id": tile.entity_id,
                            "label": tile.label,
                            "action": tile.action,
                            "icon": tile.icon,
                            "info": tile.info,
                            "order": tile.order,
                            "visible": tile.visible,
                            "accent": tile.accent,
                            "show_on_home": tile.show_on_home,
                        }
                        for tile in page.tiles
                    ],
                }
                for page in config.dashboard.pages
            ],
        },
    }


def _dashboard_yaml(config: AppConfig) -> str:
    return yaml.safe_dump({"dashboard": _config_payload(config)["dashboard"]}, sort_keys=False, allow_unicode=True)


def _dashboard_pages_summary(config: AppConfig) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page in config.dashboard.pages:
        pages.append(
            {
                "id": page.id,
                "label": page.label,
                "tiles": [
                    {
                        "id": tile.id,
                        "type": tile.type,
                        "entity_id": tile.entity_id,
                        "label": tile.label,
                        "action": tile.action,
                    }
                    for tile in page.tiles
                ],
            }
        )
    return pages


def _dashboard_data(config: AppConfig) -> dict[str, Any]:
    return {
        "pages": [
            {
                "id": page.id,
                "label": page.label,
                "visible": page.visible,
                "order": page.order,
                "tiles": [
                    {
                        "id": tile.id,
                        "page": tile.page,
                        "type": tile.type,
                        "entity_id": tile.entity_id,
                        "label": tile.label,
                        "action": tile.action,
                        "icon": tile.icon,
                        "info": tile.info,
                        "order": tile.order,
                        "visible": tile.visible,
                        "accent": tile.accent,
                        "show_on_home": tile.show_on_home,
                    }
                    for tile in page.tiles
                ],
            }
            for page in config.dashboard.pages
        ]
    }


def _dashboard_state_for_entity(entity_id: str) -> tuple[str, str]:
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    if domain in {"light", "switch", "input_boolean"}:
        return "entity", "toggle"
    if domain in {"sensor", "binary_sensor"}:
        return "sensor", "none"
    if domain in {"script", "automation", "scene"}:
        return domain, "trigger"
    return "entity", "toggle"


def _dashboard_validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    pages = data.get("pages", [])
    if not isinstance(pages, list):
        return ["Dashboard pages must be a list."]
    seen_pages: set[str] = set()
    seen_tiles: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            errors.append("Dashboard page must be a mapping.")
            continue
        page_id = str(page.get("id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", page_id):
            errors.append(f"Invalid page id: {page_id or '<empty>'}")
        if page_id in seen_pages:
            errors.append(f"Duplicate page id: {page_id}")
        seen_pages.add(page_id)
        tiles = page.get("tiles", [])
        if not isinstance(tiles, list):
            errors.append(f"Tiles for page {page_id} must be a list.")
            continue
        seen_entities: set[str] = set()
        for tile in tiles:
            if not isinstance(tile, dict):
                errors.append(f"Tile in page {page_id} must be a mapping.")
                continue
            tile_id = str(tile.get("id", "")).strip()
            entity_id = str(tile.get("entity_id", "")).strip()
            tile_type = str(tile.get("type", "")).strip() or "entity"
            action = str(tile.get("action", "")).strip() or "toggle"
            if not re.fullmatch(r"[A-Za-z0-9_-]+", tile_id):
                errors.append(f"Invalid tile id: {tile_id or '<empty>'}")
            if tile_id in seen_tiles:
                errors.append(f"Duplicate tile id: {tile_id}")
            seen_tiles.add(tile_id)
            if tile_type != "info" and not entity_id:
                errors.append(f"Tile {tile_id} on page {page_id} needs an entity_id.")
            if entity_id and entity_id in seen_entities:
                errors.append(f"Duplicate entity on page {page_id}: {entity_id}")
            if entity_id:
                seen_entities.add(entity_id)
                domain = entity_id.split(".", 1)[0]
                allowed = {
                    "light": {"toggle", "on", "off"},
                    "switch": {"toggle", "on", "off"},
                    "input_boolean": {"toggle", "on", "off"},
                    "sensor": {"none"},
                    "binary_sensor": {"none"},
                    "script": {"trigger"},
                    "automation": {"trigger"},
                    "scene": {"trigger"},
                }.get(domain)
                if allowed is not None and action not in allowed:
                    errors.append(f"Action '{action}' is invalid for {entity_id}.")
    return errors


def _dashboard_update_from_form(data: dict[str, Any], form: dict[str, str]) -> tuple[bool, str, dict[str, Any]]:
    dashboard = data.setdefault("dashboard", {})
    pages = dashboard.setdefault("pages", [])
    action = form.get("dashboard_action", "").strip()
    page_id = form.get("page_id", "").strip()
    tile_id = form.get("tile_id", "").strip()
    if action == "add_page":
        new_id = form.get("new_page_id", "").strip()
        label = form.get("new_page_label", "").strip() or new_id.title()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", new_id):
            return False, "Invalid page id.", data
        pages.append({"id": new_id, "label": label, "visible": True, "order": len(pages), "tiles": []})
    elif action in {"save_page", "toggle_page", "move_page_up", "move_page_down"}:
        page = next((item for item in pages if isinstance(item, dict) and str(item.get("id", "")) == page_id), None)
        if page is None:
            return False, "Page not found.", data
        if action == "save_page":
            new_label = form.get("page_label", "").strip() or page_id
            page["label"] = new_label
            page["visible"] = form.get("page_visible", "off") == "on"
            try:
                page["order"] = int(form.get("page_order", page.get("order", 0)))
            except ValueError:
                return False, "Invalid page order.", data
        elif action == "toggle_page":
            page["visible"] = not bool(page.get("visible", True))
        else:
            idx = pages.index(page)
            swap = idx - 1 if action == "move_page_up" else idx + 1
            if 0 <= swap < len(pages):
                pages[idx], pages[swap] = pages[swap], pages[idx]
                pages[idx]["order"] = idx
                pages[swap]["order"] = swap
    elif action in {"save_tile", "delete_tile", "move_tile_up", "move_tile_down", "copy_tile_home"}:
        page = next((item for item in pages if isinstance(item, dict) and str(item.get("id", "")) == page_id), None)
        if page is None:
            return False, "Page not found.", data
        tiles = page.setdefault("tiles", [])
        tile = next((item for item in tiles if isinstance(item, dict) and str(item.get("id", "")) == tile_id), None)
        if action == "delete_tile":
            if tile is None:
                return False, "Tile not found.", data
            tiles.remove(tile)
        elif action in {"move_tile_up", "move_tile_down"}:
            if tile is None:
                return False, "Tile not found.", data
            idx = tiles.index(tile)
            swap = idx - 1 if action == "move_tile_up" else idx + 1
            if 0 <= swap < len(tiles):
                tiles[idx], tiles[swap] = tiles[swap], tiles[idx]
                tiles[idx]["order"] = idx
                tiles[swap]["order"] = swap
        elif action == "copy_tile_home":
            if tile is None:
                return False, "Tile not found.", data
            home = next((item for item in pages if isinstance(item, dict) and str(item.get("id", "")) == "home"), None)
            if home is None:
                return False, "Home page not found.", data
            copied = dict(tile)
            copied["id"] = f"{tile_id}_home"
            copied["page"] = "home"
            copied["show_on_home"] = True
            copied["order"] = len(home.setdefault("tiles", []))
            home["tiles"].append(copied)
        elif action == "save_tile":
            raw_entity = form.get("entity_id", "").strip()
            raw_type = form.get("type", "").strip()
            raw_action = form.get("action", "").strip()
            raw_label = form.get("label", "").strip()
            raw_icon = form.get("icon", "").strip()
            raw_info = form.get("info", "").strip()
            raw_accent = form.get("accent", "").strip()
            raw_visible = form.get("visible", "off") == "on"
            raw_show_on_home = form.get("show_on_home", "off") == "on"
            try:
                raw_order = int(form.get("order", tile.get("order", 0) if tile else 0))
            except ValueError:
                return False, "Invalid tile order.", data
            if not tile:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", tile_id):
                    return False, "Invalid tile id.", data
                tile = {
                    "id": tile_id,
                    "page": page_id,
                    "type": raw_type or "entity",
                    "entity_id": raw_entity,
                    "label": raw_label,
                    "action": raw_action or "toggle",
                    "icon": raw_icon,
                    "info": raw_info,
                    "order": raw_order,
                    "visible": raw_visible,
                    "accent": raw_accent,
                    "show_on_home": raw_show_on_home,
                }
                tiles.append(tile)
            else:
                tile.update(
                    {
                        "page": page_id,
                        "type": raw_type or tile.get("type", "entity"),
                        "entity_id": raw_entity,
                        "label": raw_label,
                        "action": raw_action or tile.get("action", "toggle"),
                        "icon": raw_icon,
                        "info": raw_info,
                        "order": raw_order,
                        "visible": raw_visible,
                        "accent": raw_accent,
                        "show_on_home": raw_show_on_home,
                    }
                )
    else:
        return False, "Unsupported dashboard action.", data

    data["dashboard"] = dashboard
    errors = _dashboard_validate(dashboard)
    if errors:
        return False, "; ".join(errors), data
    return True, "Dashboard updated.", data


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


def _merge_home_assistant_config(
    current: dict[str, Any],
    form: dict[str, str],
    *,
    delete_token: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
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


def _merge_dashboard_config(current: dict[str, Any], form: dict[str, str]) -> tuple[bool, str, dict[str, Any]]:
    merged = dict(current)
    raw = form.get("dashboard_yaml", "").strip()
    if not raw:
        return False, "Dashboard configuration must not be empty.", merged
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return False, f"Invalid dashboard YAML: {exc}", merged
    if not isinstance(parsed, dict):
        return False, "Dashboard configuration must be a mapping.", merged
    dashboard = parsed.get("dashboard", parsed)
    if not isinstance(dashboard, dict):
        return False, "Dashboard section must be a mapping.", merged
    pages = dashboard.get("pages", [])
    if not isinstance(pages, list):
        return False, "Dashboard pages must be a list.", merged
    merged["dashboard"] = dashboard
    errors = _dashboard_validate(dashboard)
    if errors:
        return False, "; ".join(errors), merged
    return True, "Dashboard updated.", merged


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
      <p class="muted">Lokale Recovery-, Konfigurations- und Diagnoseoberfläche auf Port 8765.</p>
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
          <a class="btn" href="{{ url_for('restart_panel') }}">Panel neu starten</a>
          <a class="btn" href="{{ url_for('healthcheck') }}">Healthcheck</a>
        </div>
        <div class="card">
          <h2>Home Assistant</h2>
          <p class="muted">URL: {{ config.home_assistant.url }}</p>
          <p class="muted">Token vorhanden: {{ 'Ja' if config.home_assistant.token.strip() else 'Nein' }}</p>
          <a class="btn primary" href="{{ url_for('home_assistant_page') }}">Öffnen</a>
          <a class="btn" href="{{ url_for('dashboard_page') }}">Dashboard</a>
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
        input, textarea { width:100%; box-sizing:border-box; background:#0d1116; color:var(--text); border:1px solid #324354; border-radius:12px; padding:10px 12px; margin:4px 0 12px; }
        textarea { min-height: 240px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
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


def _render_dashboard(config: AppConfig, message: str = "", error: str = "", page_id: str = "", tile_id: str = "") -> str:
    client = _ha_client(config)
    entity_rows = _entity_rows(client)
    dashboard = _dashboard_data(config)
    pages = dashboard.get("pages", [])
    if not page_id and pages:
        page_id = str(pages[0].get("id", ""))
    selected_page = next((page for page in pages if str(page.get("id", "")) == page_id), pages[0] if pages else {})
    selected_tiles = selected_page.get("tiles", []) if isinstance(selected_page, dict) else []
    selected_tile = next((tile for tile in selected_tiles if str(tile.get("id", "")) == tile_id), selected_tiles[0] if selected_tiles else {})
    template = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Dashboard - Hyrovi Touch Admin</title>
      <style>
        :root { color-scheme: dark; --bg:#0f1318; --panel:#18212b; --panel2:#202b36; --text:#eef3f7; --muted:#9fb0bf; --ok:#4dd48a; --bad:#ff7b7b; --accent:#59a4ff; }
        body { margin:0; font-family: system-ui, sans-serif; background: radial-gradient(circle at top, #18212b, #0f1318 60%); color: var(--text); }
        .wrap { max-width: 1400px; margin: 0 auto; padding: 24px; }
        .grid { display:grid; gap:16px; }
        .layout { grid-template-columns: 240px minmax(0, 1.2fr) 360px; align-items:start; }
        .card { background: rgba(24,33,43,.94); border:1px solid #273340; border-radius:18px; padding:18px; box-shadow:0 20px 50px rgba(0,0,0,.25); }
        h1,h2,h3 { margin:0 0 12px 0; }
        .muted { color: var(--muted); }
        .btn { display:inline-block; margin:4px 6px 0 0; padding:10px 14px; border-radius:14px; background: var(--panel2); color: var(--text); text-decoration:none; border:1px solid #324354; }
        .btn.primary { background: linear-gradient(135deg, #2e7dff, #64b5ff); color:#06111f; font-weight:700; }
        .btn.danger { background:#4a1f24; border-color:#853645; }
        input, select, textarea { width:100%; box-sizing:border-box; background:#0d1116; color:var(--text); border:1px solid #324354; border-radius:12px; padding:10px 12px; margin:4px 0 12px; }
        textarea { min-height: 220px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre; }
        label { display:block; margin-top:10px; font-weight:600; }
        .page-item, .tile-item { background:#10151b; border:1px solid #2b3744; border-radius:16px; padding:12px; margin-bottom:10px; }
        .page-item.active { border-color: var(--accent); box-shadow: 0 0 0 1px rgba(89,164,255,.35) inset; }
        .tile-preview { padding:14px; border-radius:18px; border:2px solid #364455; background:#151b23; margin-bottom:10px; }
        .tile-preview .name { font-weight:700; margin-bottom:6px; }
        .tile-preview .meta { color: var(--muted); font-size:.9rem; line-height:1.35; }
        .tile-preview.on-light { background:#c68f30; color:#140e05; border-color:#d6aa60; }
        .tile-preview.on-switch { background:#388ec8; color:#eef7ff; border-color:#77b2dc; }
        .tile-preview.on-boolean { background:#4abc7c; color:#07140d; border-color:#80d29f; }
        .tile-preview.off { background:#151b23; color:var(--text); border-color:#3f4b57; }
        .tile-preview.sensor { background:#1c2430; color:var(--text); border-color:#44607b; }
        .tile-preview.action { background:#354662; color:var(--text); border-color:#6c8bd1; }
        .tile-preview.unavailable { background:#151b23; color:var(--text); border-color:#d64a4a; }
        .tile-preview.unknown { background:#151b23; color:var(--text); border-color:#e08d3b; }
        .toolbar { display:flex; gap:8px; flex-wrap:wrap; }
        table { width:100%; border-collapse: collapse; }
        th, td { text-align:left; padding:8px 6px; border-bottom:1px solid #273340; vertical-align:top; }
        .sticky { position: sticky; top: 16px; }
        details summary { cursor: pointer; font-weight:700; }
      </style>
      <script>
        function filterEntities() {
          const query = document.getElementById('entity-filter').value.toLowerCase();
          document.querySelectorAll('[data-entity-row]').forEach((row) => {
            row.style.display = row.dataset.search.includes(query) ? '' : 'none';
          });
        }
        function fillTile(entityId, friendly, domain, state) {
          const form = document.getElementById('tile-form');
          form.entity_id.value = entityId;
          form.label.value = friendly || entityId;
          if (domain === 'light' || domain === 'switch' || domain === 'input_boolean') {
            form.type.value = 'entity';
            form.action.value = 'toggle';
          } else if (domain === 'sensor') {
            form.type.value = 'sensor';
            form.action.value = 'none';
          } else if (domain === 'binary_sensor') {
            form.type.value = 'binary_sensor';
            form.action.value = 'none';
          } else if (domain === 'script' || domain === 'automation' || domain === 'scene') {
            form.type.value = domain;
            form.action.value = 'trigger';
          }
          form.page_id.focus();
          form.page_id.scrollIntoView({behavior:'smooth', block:'center'});
        }
      </script>
    </head>
    <body>
    <div class="wrap">
      <h1>Dashboard</h1>
      <p class="muted">Seiten und Karten werden hier visuell verwaltet. YAML ist nur noch unter "Erweitert" verfügbar.</p>
      {% if message %}<div class="card" style="border-color:#43627e; margin-bottom:16px;">{{ message }}</div>{% endif %}
      {% if error %}<div class="card" style="border-color:#8b4a4a; margin-bottom:16px; color:var(--bad);">{{ error }}</div>{% endif %}
      <div class="grid layout">
        <div class="card sticky">
          <h2>Seiten</h2>
          {% for page in pages %}
            <div class="page-item {% if page.id == selected_page.id %}active{% endif %}">
              <div><strong>{{ page.label }}</strong></div>
              <div class="muted">{{ page.id }} · {{ page.tiles|length }} Karten · {{ 'sichtbar' if page.visible else 'ausgeblendet' }}</div>
              <div class="toolbar">
                <a class="btn" href="{{ url_for('dashboard_page', page_id=page.id) }}">Öffnen</a>
                <form method="post" action="{{ url_for('dashboard_save') }}" style="display:inline">
                  <input type="hidden" name="dashboard_action" value="toggle_page">
                  <input type="hidden" name="page_id" value="{{ page.id }}">
                  <button class="btn" type="submit">{{ 'Ausblenden' if page.visible else 'Einblenden' }}</button>
                </form>
              </div>
            </div>
          {% endfor %}
          <h3>Neue Seite</h3>
          <form method="post" action="{{ url_for('dashboard_save') }}">
            <input type="hidden" name="dashboard_action" value="add_page">
            <label>Seiten-ID</label>
            <input name="new_page_id" placeholder="z. B. garden">
            <label>Label</label>
            <input name="new_page_label" placeholder="Garten">
            <button class="btn primary" type="submit">Seite hinzufügen</button>
          </form>
        </div>
        <div class="card">
          <h2>{{ selected_page.label if selected_page else 'Keine Seite' }}</h2>
          <div class="muted">{{ selected_page.id if selected_page else '' }}</div>
          <div class="toolbar" style="margin:12px 0 18px;">
            <form method="post" action="{{ url_for('dashboard_save') }}">
              <input type="hidden" name="dashboard_action" value="save_page">
              <input type="hidden" name="page_id" value="{{ selected_page.id }}">
              <label>Label</label>
              <input name="page_label" value="{{ selected_page.label }}">
              <label>Reihenfolge</label>
              <input name="page_order" type="number" value="{{ selected_page.order }}">
              <label><input type="checkbox" name="page_visible" {% if selected_page.visible %}checked{% endif %}> Seite sichtbar</label>
              <button class="btn primary" type="submit">Seite speichern</button>
            </form>
          </div>
          <h3>Karten</h3>
          {% if selected_tiles %}
            {% for tile in selected_tiles %}
              {% set state = tile.state|lower %}
              <div class="tile-preview {% if state == 'on' %}{% if tile.type == 'sensor' %}sensor{% elif tile.type in ['script', 'automation', 'scene', 'action'] %}action{% elif tile.entity_id.startswith('light.') %}on-light{% elif tile.entity_id.startswith('switch.') %}on-switch{% elif tile.entity_id.startswith('input_boolean.') %}on-boolean{% else %}on-switch{% endif %}{% elif state == 'unavailable' %}unavailable{% elif state == 'unknown' %}unknown{% elif tile.type in ['sensor', 'binary_sensor'] %}sensor{% else %}off{% endif %}">
                <div class="name">{{ tile.label or tile.id }}</div>
                <div class="meta">
                  Entity: {{ tile.entity_id or 'kein Entity' }}<br>
                  Domain: {{ tile.entity_id.split('.')[0] if '.' in tile.entity_id else tile.type }}<br>
                  Zustand: {{ tile.state }}<br>
                  Typ: {{ tile.type }}<br>
                  Aktion: {{ tile.action }}<br>
                  Reihenfolge: {{ tile.order }}
                </div>
                <div class="toolbar" style="margin-top:10px;">
                  <a class="btn" href="{{ url_for('dashboard_page', page_id=selected_page.id, tile_id=tile.id) }}">Bearbeiten</a>
                  <form method="post" action="{{ url_for('dashboard_save') }}" style="display:inline">
                    <input type="hidden" name="dashboard_action" value="delete_tile">
                    <input type="hidden" name="page_id" value="{{ selected_page.id }}">
                    <input type="hidden" name="tile_id" value="{{ tile.id }}">
                    <button class="btn danger" type="submit">Entfernen</button>
                  </form>
                  <form method="post" action="{{ url_for('dashboard_save') }}" style="display:inline">
                    <input type="hidden" name="dashboard_action" value="move_tile_up">
                    <input type="hidden" name="page_id" value="{{ selected_page.id }}">
                    <input type="hidden" name="tile_id" value="{{ tile.id }}">
                    <button class="btn" type="submit">Nach oben</button>
                  </form>
                  <form method="post" action="{{ url_for('dashboard_save') }}" style="display:inline">
                    <input type="hidden" name="dashboard_action" value="move_tile_down">
                    <input type="hidden" name="page_id" value="{{ selected_page.id }}">
                    <input type="hidden" name="tile_id" value="{{ tile.id }}">
                    <button class="btn" type="submit">Nach unten</button>
                  </form>
                  <form method="post" action="{{ url_for('dashboard_save') }}" style="display:inline">
                    <input type="hidden" name="dashboard_action" value="copy_tile_home">
                    <input type="hidden" name="page_id" value="{{ selected_page.id }}">
                    <input type="hidden" name="tile_id" value="{{ tile.id }}">
                    <button class="btn" type="submit">Auf Home kopieren</button>
                  </form>
                </div>
              </div>
            {% endfor %}
          {% else %}
            <div class="muted">Auf dieser Seite sind noch keine Karten konfiguriert.</div>
          {% endif %}
        </div>
        <div class="card sticky">
          <h2>{% if selected_tile and selected_tile.id %}Karte bearbeiten{% else %}Entity hinzufügen{% endif %}</h2>
          <form id="tile-form" method="post" action="{{ url_for('dashboard_save') }}">
            <input type="hidden" name="dashboard_action" value="save_tile">
            <label>Seite</label>
            <select name="page_id">
              {% for page in pages %}
                <option value="{{ page.id }}" {% if page.id == selected_page.id %}selected{% endif %}>{{ page.label }}</option>
              {% endfor %}
            </select>
            <label>Karten-ID</label>
            <input name="tile_id" value="{{ selected_tile.id if selected_tile else '' }}" placeholder="z. B. living_room_light">
            <label>Entity</label>
            <input name="entity_id" value="{{ selected_tile.entity_id if selected_tile else '' }}" placeholder="switch.lampe_wohnzimmer">
            <label>Label</label>
            <input name="label" value="{{ selected_tile.label if selected_tile else '' }}">
            <label>Typ</label>
            <select name="type">
              {% for item in ['entity','sensor','binary_sensor','script','automation','scene','info','action'] %}
                <option value="{{ item }}" {% if selected_tile and selected_tile.type == item %}selected{% endif %}>{{ item }}</option>
              {% endfor %}
            </select>
            <label>Aktion</label>
            <select name="action">
              {% for item in ['toggle','none','trigger','on','off','refresh'] %}
                <option value="{{ item }}" {% if selected_tile and selected_tile.action == item %}selected{% endif %}>{{ item }}</option>
              {% endfor %}
            </select>
            <label>Icon</label>
            <input name="icon" value="{{ selected_tile.icon if selected_tile else '' }}">
            <label>Akzentfarbe</label>
            <input name="accent" value="{{ selected_tile.accent if selected_tile else '' }}" placeholder="#f2c14e">
            <label>Zusatztext</label>
            <input name="info" value="{{ selected_tile.info if selected_tile else '' }}">
            <label>Reihenfolge</label>
            <input name="order" type="number" value="{{ selected_tile.order if selected_tile else 0 }}">
            <label><input type="checkbox" name="visible" {% if not selected_tile or selected_tile.visible %}checked{% endif %}> Karte sichtbar</label>
            <label><input type="checkbox" name="show_on_home" {% if selected_tile and selected_tile.show_on_home %}checked{% endif %}> Auf Home anzeigen</label>
            <button class="btn primary" type="submit">Speichern</button>
          </form>
          <h3 style="margin-top:18px;">Entities</h3>
          <input id="entity-filter" oninput="filterEntities()" placeholder="entity_id, Friendly Name, Domain, Zustand">
          <div style="max-height: 250px; overflow:auto;">
            <table>
              <thead><tr><th>Entity-ID</th><th>Name</th><th>Domain</th><th>Zustand</th></tr></thead>
              <tbody>
                {% for row in entity_rows %}
                  <tr data-entity-row data-search="{{ (row.entity_id ~ ' ' ~ row.friendly_name ~ ' ' ~ row.domain ~ ' ' ~ row.state)|lower }}">
                    <td><a href="#" onclick="fillTile({{ row.entity_id|tojson }}, {{ row.friendly_name|tojson }}, {{ row.domain|tojson }}, {{ row.state|tojson }}); return false;">{{ row.entity_id }}</a></td>
                    <td>{{ row.friendly_name }}</td>
                    <td>{{ row.domain }}</td>
                    <td>{{ row.state }}</td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          <details style="margin-top:16px;">
            <summary>Erweitert</summary>
            <form method="post" action="{{ url_for('dashboard_save') }}">
              <input type="hidden" name="dashboard_action" value="save_raw">
              <textarea name="dashboard_yaml">{{ dashboard_yaml }}</textarea>
              <button class="btn" type="submit">YAML speichern</button>
            </form>
          </details>
        </div>
      </div>
    </div>
    </body>
    </html>
    """
    return render_template_string(
        template,
        pages=pages,
        selected_page=selected_page or {"id": "", "label": "", "visible": True, "order": 0},
        selected_tiles=selected_tiles,
        selected_tile=selected_tile or {"id": "", "entity_id": "", "label": "", "type": "entity", "action": "toggle", "icon": "", "info": "", "order": 0, "visible": True, "accent": "", "show_on_home": False},
        entity_rows=entity_rows,
        dashboard_yaml=_dashboard_yaml(config),
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
        if request.path == "/health":
            return None
        if not _auth_ok(current_config()):
            return _auth_challenge()
        return None

    @app.get("/")
    def index() -> str:
        return _render_index(current_config())

    @app.get("/health")
    def healthcheck() -> Response:
        report = run_doctor(config_path)
        return _json_response(report.to_dict() | {"ok": report.ok}, 200 if report.ok else 503)

    @app.get("/healthcheck")
    def healthcheck_page() -> str:
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

    @app.get("/restart-panel")
    def restart_panel() -> Response:
        _restart_panel_service()
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
        _restart_panel_service()
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
        _restart_panel_service()
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
                parts.append(
                    f"{label}: {result.detail if not result.ok else result.data.get('state', 'unknown') if isinstance(result.data, dict) else 'ok'}"
                )
        message = " | ".join(parts)
        return _render_home_assistant(config, message=message)

    @app.get("/dashboard")
    def dashboard_page() -> str:
        return _render_dashboard(
            current_config(),
            page_id=request.args.get("page_id", ""),
            tile_id=request.args.get("tile_id", ""),
        )

    @app.post("/dashboard/save")
    def dashboard_save() -> str:
        config = current_config()
        raw = read_config_data(config_path)
        before = load_config(config_path)
        action = request.form.get("dashboard_action", "").strip()
        if action == "save_raw":
            ok, detail, merged = _merge_dashboard_config(raw, request.form)
        else:
            ok, detail, merged = _dashboard_update_from_form(raw, request.form)
        if not ok:
            return _render_dashboard(config, error=detail, page_id=request.form.get("page_id", ""), tile_id=request.form.get("tile_id", ""))
        try:
            _ = load_config(config_path)
        except Exception as exc:
            return _render_dashboard(config, error=f"Konfiguration konnte nicht geladen werden: {exc}", page_id=request.form.get("page_id", ""), tile_id=request.form.get("tile_id", ""))
        saved, save_detail = _save_config_data(merged)
        if not saved:
            return _render_dashboard(config, error=save_detail, page_id=request.form.get("page_id", ""), tile_id=request.form.get("tile_id", ""))
        _restart_panel_service()
        reloaded = load_config(config_path)
        health = _ha_client(reloaded).healthcheck()
        if not health.ok and before.raw:
            _save_config_data(before.raw)
            _restart_panel_service()
            return _render_dashboard(before, error=f"Panel-Healthcheck fehlgeschlagen: {health.detail}", page_id=request.form.get("page_id", ""), tile_id=request.form.get("tile_id", ""))
        return _render_dashboard(reloaded, message="Dashboard gespeichert und Panel-Service neu gestartet.", page_id=request.form.get("page_id", ""), tile_id=request.form.get("tile_id", ""))

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

    @app.get("/api/dashboard")
    def dashboard_api() -> Response:
        config = current_config()
        return _json_response({"ok": True, "dashboard": _config_payload(config)["dashboard"]})

    return app


def main() -> int:
    app = create_app(CONFIG_FILE)
    app.run(host="0.0.0.0", port=8765, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
