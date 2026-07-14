from __future__ import annotations

import base64
import html
import subprocess
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, render_template_string, request, url_for

from app.config.loader import AppConfig, load_config
from app.doctor import run_doctor
from app.runtime import CONFIG_FILE, INSTALL_ROOT, PREVIOUS_LINK, current_release_dir, read_release_metadata
from app.update import UpdateError, list_installed_releases, rollback_release, update_release


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


def create_app(config_path: Path = CONFIG_FILE) -> Flask:
    app = Flask(__name__)
    config = load_config(config_path)
    app.config["HYROVI_CONFIG"] = config

    @app.before_request
    def _check_auth() -> Response | None:
        if not _auth_ok(config):
            return _auth_challenge()
        return None

    @app.get("/")
    def index() -> str:
        report = run_doctor(config_path)
        releases = list_installed_releases()
        info = _release_info()
        services = {
            "panel": _systemctl_status("hyrovi-touch-panel.service"),
            "admin": _systemctl_status("hyrovi-touch-admin.service"),
            "update": _systemctl_status("hyrovi-touch-update-on-boot.service"),
        }
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
          <p class="muted">Lokale Recovery- und Diagnoseoberflache auf Port 8765.</p>
          <div class="grid">
            <div class="card">
              <h2>Status</h2>
              <div class="{{ 'ok' if report.ok else 'bad' }}">{{ 'Gesund' if report.ok else 'Pruefung fehlgeschlagen' }}</div>
              <p class="muted">Systemd: Panel={{ services.panel }}, Admin={{ services.admin }}, Update={{ services.update }}</p>
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
        )

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
            update_release(config)
        except UpdateError as exc:
            return Response(f"Update failed: {exc}", 500)
        return redirect(url_for("index"))

    @app.get("/rollback-now")
    def rollback_now() -> Response:
        try:
            rollback_release()
        except UpdateError as exc:
            return Response(f"Rollback failed: {exc}", 500)
        return redirect(url_for("index"))

    return app


def main() -> int:
    app = create_app(CONFIG_FILE)
    app.run(host="0.0.0.0", port=8765, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
