from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


INSTALL_ROOT = Path(os.environ.get("HYROVI_INSTALL_ROOT", "/opt/hyrovi-touch-panel"))
RELEASES_DIR = INSTALL_ROOT / "releases"
CURRENT_LINK = INSTALL_ROOT / "current"
PREVIOUS_LINK = INSTALL_ROOT / "previous"
SHARED_DIR = INSTALL_ROOT / "shared"
VENV_DIR = INSTALL_ROOT / "venv"
CONFIG_DIR = Path(os.environ.get("HYROVI_CONFIG_DIR", "/etc/hyrovi-touch-panel"))
CONFIG_FILE = Path(os.environ.get("HYROVI_CONFIG_FILE", str(CONFIG_DIR / "config.yaml")))
STATE_DIR = Path(os.environ.get("HYROVI_STATE_DIR", "/var/lib/hyrovi-touch-panel"))
LOG_DIR = Path(os.environ.get("HYROVI_LOG_DIR", "/var/log/hyrovi-touch-panel"))
SYSTEMD_DIR = Path(os.environ.get("HYROVI_SYSTEMD_DIR", "/etc/systemd/system"))
USER_NAME = "hyrovi-panel"
PANEL_SERVICE = "hyrovi-touch-panel.service"
ADMIN_SERVICE = "hyrovi-touch-admin.service"
UPDATE_SERVICE = "hyrovi-touch-update-on-boot.service"


@dataclass(slots=True)
class ReleaseMetadata:
    version: str
    ref: str
    channel: str
    source: str
    git_sha: str
    created_at: str


def now_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def release_metadata_path(release_dir: Path) -> Path:
    return release_dir / "release.json"


def read_release_metadata(release_dir: Path | None) -> ReleaseMetadata | None:
    if release_dir is None:
        return None
    path = release_metadata_path(release_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReleaseMetadata(**data)


def write_release_metadata(release_dir: Path, metadata: ReleaseMetadata) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    release_metadata_path(release_dir).write_text(
        json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_symlink(path: Path) -> Path | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        return None


def current_release_dir() -> Path | None:
    return resolve_symlink(CURRENT_LINK)


def previous_release_dir() -> Path | None:
    return resolve_symlink(PREVIOUS_LINK)


def ensure_base_directories() -> None:
    for path in (INSTALL_ROOT, RELEASES_DIR, SHARED_DIR, CONFIG_DIR, STATE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def as_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)
