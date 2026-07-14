from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from app.config.loader import AppConfig, HomeAssistantUrlError, load_config
from app.ha.client import HomeAssistantClient
from app.runtime import (
    ADMIN_SERVICE,
    CONFIG_FILE,
    CURRENT_LINK,
    INSTALL_ROOT,
    LOG_DIR,
    PANEL_SERVICE,
    PREVIOUS_LINK,
    RELEASES_DIR,
    SYSTEMD_DIR,
    UPDATE_SERVICE,
    VENV_DIR,
    current_release_dir,
    read_release_metadata,
)


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(slots=True)
class DoctorReport:
    checks: list[CheckResult]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def format_text(self) -> str:
        lines = []
        for check in self.checks:
            state = "OK" if check.ok else "FAIL"
            lines.append(f"[{state}] {check.name}: {check.detail}")
        lines.append(f"Result: {'OK' if self.ok else 'FAIL'}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": check.name, "ok": check.ok, "detail": check.detail}
                for check in self.checks
            ],
        }


def _check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


def _run_py_compile(paths: Iterable[Path]) -> tuple[bool, str]:
    files = [path for path in paths if path.suffix == ".py" and path.exists()]
    if not files:
        return False, "No Python files found."
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except Exception as exc:
            return False, f"{path}: {exc}"
    return True, "Python syntax check passed."


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    ]


def _display_plausible() -> tuple[bool, str]:
    if any(os.environ.get(var) for var in ("DISPLAY", "WAYLAND_DISPLAY", "SDL_VIDEODRIVER")):
        return True, "Display environment variables are present."
    if Path("/dev/fb0").exists() or Path("/dev/dri").exists():
        return True, "Framebuffer or DRM device detected."
    return False, "No obvious display environment or framebuffer found."


def _touch_plausible() -> tuple[bool, str]:
    proc = subprocess.run(["libinput", "list-devices"], text=True, capture_output=True)
    if proc.returncode == 0:
        blocks = [block.strip() for block in proc.stdout.split("\n\n") if block.strip()]
        for block in blocks:
            lower = block.lower()
            if "capabilities:" in lower and "touch" in lower:
                return True, "libinput reports a device with Capabilities: touch."
    fallback = Path("/proc/bus/input/devices")
    if fallback.exists():
        content = fallback.read_text(encoding="utf-8", errors="ignore").lower()
        if "touch" in content:
            return True, "Touch hints found in /proc/bus/input/devices."
    return False, "No clear touchscreen entry found via libinput."


def _ha_check(config: AppConfig) -> CheckResult:
    client = HomeAssistantClient.from_config(config)
    result = client.healthcheck()
    if result.ok and result.source == "mock":
        return _check("Home Assistant", True, result.detail)
    return _check("Home Assistant", result.ok, result.detail)


def _ha_url_check(config: AppConfig) -> CheckResult:
    if not config.ha_enabled:
        return _check("HA URL", True, "Skipped: Home Assistant URL/token not configured.")

    client = HomeAssistantClient.from_config(config)
    try:
        url = client._api_url(trailing_slash=True)
    except HomeAssistantUrlError as exc:
        return _check("HA URL", False, f"Invalid Home Assistant URL: {exc}")

    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {client.token}"}, timeout=4.0)
        ok = response.ok
        detail = f"HA URL reachable: HTTP {response.status_code}"
    except requests.RequestException as exc:
        ok = False
        detail = f"HA URL check failed: {exc}"
    return _check("HA URL", ok, detail)


def run_doctor(config_path: Path = CONFIG_FILE) -> DoctorReport:
    config = load_config(config_path)
    checks: list[CheckResult] = []

    checks.append(_check("Install root", INSTALL_ROOT.exists(), str(INSTALL_ROOT)))
    checks.append(_check("Releases dir", RELEASES_DIR.exists(), str(RELEASES_DIR)))
    checks.append(_check("Current link", CURRENT_LINK.exists() or CURRENT_LINK.is_symlink(), str(CURRENT_LINK)))
    checks.append(_check("Previous link", PREVIOUS_LINK.exists() or PREVIOUS_LINK.is_symlink(), str(PREVIOUS_LINK)))
    checks.append(_check("Venv", (VENV_DIR / "bin" / "python").exists(), str(VENV_DIR)))
    checks.append(_check("Config", config.exists, str(config_path)))
    checks.append(_check("Systemd panel service", (SYSTEMD_DIR / PANEL_SERVICE).exists(), str(SYSTEMD_DIR / PANEL_SERVICE)))
    checks.append(_check("Systemd admin service", (SYSTEMD_DIR / ADMIN_SERVICE).exists(), str(SYSTEMD_DIR / ADMIN_SERVICE)))
    checks.append(_check("Systemd update service", (SYSTEMD_DIR / UPDATE_SERVICE).exists(), str(SYSTEMD_DIR / UPDATE_SERVICE)))
    checks.append(_check("Logs dir", LOG_DIR.exists(), str(LOG_DIR)))

    release = current_release_dir()
    if release is not None:
        metadata = read_release_metadata(release)
        checks.append(_check("Current release metadata", metadata is not None, str(release)))
        python_files = _python_files(release)
        ok, detail = _run_py_compile(python_files)
        checks.append(_check("Python syntax", ok, detail))
        if metadata is not None:
            checks.append(_check("Current version", True, metadata.version))
        else:
            checks.append(_check("Current version", False, "release.json missing"))
    else:
        checks.append(_check("Current release metadata", False, "No current release selected."))
        checks.append(_check("Python syntax", False, "No release to validate."))
        checks.append(_check("Current version", False, "Unknown"))

    display_ok, display_detail = _display_plausible()
    checks.append(_check("Display", display_ok, display_detail))
    touch_ok, touch_detail = _touch_plausible()
    checks.append(_check("Touch", touch_ok, touch_detail))
    checks.append(_ha_check(config))
    checks.append(_ha_url_check(config))

    return DoctorReport(checks=checks)
