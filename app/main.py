from __future__ import annotations

import argparse
from pathlib import Path

from app.config.loader import AppConfig, load_config
from app.runtime import CONFIG_FILE
from app.ui.dashboard import DashboardApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hyrovi Touch Panel")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="Path to config.yaml.")
    parser.add_argument("--fullscreen", action="store_true", help="Force fullscreen mode.")
    parser.add_argument("--windowed", action="store_true", help="Force windowed mode.")
    return parser.parse_args()


def resolve_config(args: argparse.Namespace) -> AppConfig:
    config = load_config(Path(args.config))
    if args.fullscreen and args.windowed:
        raise SystemExit("Choose either --fullscreen or --windowed, not both.")
    if args.fullscreen:
        config.ui.fullscreen = True
    if args.windowed:
        config.ui.fullscreen = False
    return config


def main() -> int:
    args = parse_args()
    config = resolve_config(args)
    app = DashboardApp(config)
    return app.run()
