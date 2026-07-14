from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config.loader import load_config
from app.doctor import run_doctor
from app.ha.client import HomeAssistantClient
from app.runtime import CONFIG_FILE, current_release_dir, read_release_metadata
from app.update import UpdateError, rollback_release, update_release


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hyrovi-panel")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="Path to the panel config.yaml.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("doctor")
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--on-boot", action="store_true", help="Run the boot update path.")
    sub.add_parser("rollback")
    sub.add_parser("logs")
    sub.add_parser("restart")
    sub.add_parser("touch-test")
    sub.add_parser("display-test")
    sub.add_parser("ha-status")
    sub.add_parser("ha-test")
    sub.add_parser("ha-entities")
    return parser


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["/usr/bin/systemctl", *args]
    if sys.platform != "win32":
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            return proc
        return subprocess.run(["sudo", "-n", *cmd], text=True, capture_output=True)
    return subprocess.run(cmd, text=True, capture_output=True)


def _status(args: argparse.Namespace) -> int:
    report = run_doctor(Path(args.config))
    release = current_release_dir()
    metadata = read_release_metadata(release) if release else None
    print(f"Release: {release if release else 'unknown'}")
    print(f"Version: {metadata.version if metadata else 'unknown'}")
    print(f"Config: {args.config}")
    print(f"Status: {'ok' if report.ok else 'fail'}")
    print(report.format_text())
    return 0 if report.ok else 1


def _doctor(args: argparse.Namespace) -> int:
    report = run_doctor(Path(args.config))
    print(report.format_text())
    return 0 if report.ok else 1


def _rollback(args: argparse.Namespace) -> int:
    try:
        outcome = rollback_release(Path(args.config))
    except UpdateError as exc:
        print(f"Rollback failed: {exc}")
        return 1
    print(outcome.message)
    return 0 if outcome.ok else 1


def _logs(args: argparse.Namespace) -> int:
    proc = subprocess.run(["journalctl", "-u", "hyrovi-touch-panel.service", "-n", "200", "--no-pager"], text=True, capture_output=True)
    print(proc.stdout or proc.stderr)
    return proc.returncode


def _restart(args: argparse.Namespace) -> int:
    results = [
        _systemctl("restart", "hyrovi-touch-panel.service"),
        _systemctl("restart", "hyrovi-touch-admin.service"),
    ]
    for proc in results:
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "restart failed")
            return proc.returncode
    return 0


def _touch_test(args: argparse.Namespace) -> int:
    from app.ui.diagnostics import run_touch_test

    config = load_config(Path(args.config))
    return run_touch_test(config.display_size, fullscreen=config.ui.fullscreen)


def _display_test(args: argparse.Namespace) -> int:
    from app.ui.diagnostics import run_display_test

    config = load_config(Path(args.config))
    return run_display_test(config.display_size, fullscreen=config.ui.fullscreen)


def _ha_client(args: argparse.Namespace) -> tuple[HomeAssistantClient, Any]:
    config = load_config(Path(args.config))
    return HomeAssistantClient.from_config(config), config


def _ha_status(args: argparse.Namespace) -> int:
    client, config = _ha_client(args)
    result = client.healthcheck()
    connected = result.ok and result.source == "ha"
    print(f"URL: {config.home_assistant.url or 'unset'}")
    print(f"Token configured: {'yes' if bool(config.home_assistant.token.strip()) else 'no'}")
    print(f"Connected: {'yes' if connected else 'no'}")
    print(f"Mode: {'mock' if result.source == 'mock' else 'real'}")
    print(f"Detail: {result.detail}")
    if client.enabled and not result.ok:
        return 1
    return 0


def _ha_test(args: argparse.Namespace) -> int:
    client, config = _ha_client(args)
    problems = 0

    api_result = client.healthcheck()
    print(f"API /api/: {'ok' if api_result.ok else 'fail'} - {api_result.detail}")
    if client.enabled and not api_result.ok:
        problems += 1

    for label, entity_id in (
        ("main_light", config.entities.main_light),
        ("temperature", config.entities.temperature),
        ("humidity", config.entities.humidity),
    ):
        result = client.get_state(entity_id)
        if result.ok and isinstance(result.data, dict):
            state = result.data.get("state", "unknown")
            print(f"{label}: ok - {entity_id} = {state}")
        else:
            problems += 1
            print(f"{label}: fail - {result.detail}")

    return 1 if problems else 0


def _ha_entities(args: argparse.Namespace) -> int:
    client, _config = _ha_client(args)
    result = client.list_states()
    if not result.ok or not isinstance(result.data, list):
        print(f"Unable to list Home Assistant entities: {result.detail}")
        return 1

    print(f"{'ENTITY ID':40} {'FRIENDLY NAME':28} {'DOMAIN':16} STATE")
    print("-" * 96)
    for entity in sorted(result.data, key=lambda item: str(item.get("entity_id", ""))):
        entity_id = str(entity.get("entity_id", ""))
        attributes = entity.get("attributes", {}) if isinstance(entity, dict) else {}
        friendly_name = str(attributes.get("friendly_name", "")) if isinstance(attributes, dict) else ""
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        state = str(entity.get("state", "")) if isinstance(entity, dict) else ""
        print(f"{entity_id:40.40} {friendly_name:28.28} {domain:16.16} {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return _status(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "update":
        try:
            outcome = update_release(config_path=Path(args.config), on_boot=args.on_boot)
        except UpdateError as exc:
            print(f"Update failed: {exc}")
            return 1
        print(outcome.message)
        if outcome.release_dir:
            print(f"Release: {outcome.release_dir}")
        if outcome.version:
            print(f"Version: {outcome.version}")
        return 0 if outcome.ok else 1
    if args.command == "rollback":
        return _rollback(args)
    if args.command == "logs":
        return _logs(args)
    if args.command == "restart":
        return _restart(args)
    if args.command == "touch-test":
        return _touch_test(args)
    if args.command == "display-test":
        return _display_test(args)
    if args.command == "ha-status":
        return _ha_status(args)
    if args.command == "ha-test":
        return _ha_test(args)
    if args.command == "ha-entities":
        return _ha_entities(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
