from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from app.config.loader import load_config
from app.doctor import run_doctor
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
    return parser


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["/usr/bin/systemctl", *args]
    if sys.platform != "win32" and hasattr(sys, "real_prefix"):
        pass
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
