from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from app.config.loader import AppConfig, load_config
from app.doctor import DoctorReport, run_doctor
from app.runtime import (
    ADMIN_SERVICE,
    CONFIG_FILE,
    CURRENT_LINK,
    INSTALL_ROOT,
    PANEL_SERVICE,
    PREVIOUS_LINK,
    RELEASES_DIR,
    ReleaseMetadata,
    current_release_dir,
    ensure_base_directories,
    now_timestamp,
    read_release_metadata,
    write_release_metadata,
)


@dataclass(slots=True)
class UpdateOutcome:
    ok: bool
    message: str
    version: str | None = None
    release_dir: Path | None = None
    doctor: DoctorReport | None = None


class UpdateError(RuntimeError):
    pass


def _repo_url(github_repo: str) -> str:
    return f"https://github.com/{github_repo}.git"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=check)


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = ["systemctl", *args]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    return _run(cmd)


def _git_tags(repo_url: str) -> list[str]:
    proc = _run(["git", "ls-remote", "--tags", "--refs", repo_url], check=False)
    if proc.returncode != 0:
        return []
    tags: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/tags/"):
            tags.append(parts[1].removeprefix("refs/tags/"))
    return tags


def _version_key(tag: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for part in tag.lstrip("v").replace("-", ".").split("."):
        if part.isdigit():
            numbers.append(int(part))
        else:
            break
    return tuple(numbers) if numbers else (-1,)


def latest_ref(config: AppConfig) -> str:
    if config.updates.channel != "stable":
        return "main"
    tags = sorted(_git_tags(_repo_url(config.updates.github_repo)), key=_version_key)
    return tags[-1] if tags else "main"


def _release_name(ref: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in ref)
    return f"{now_timestamp()}-{cleaned}"


def _release_python() -> Path:
    return INSTALL_ROOT / "venv" / "bin" / "python"


def _install_requirements(release_dir: Path) -> None:
    requirements = release_dir / "requirements.txt"
    if not requirements.exists():
        raise UpdateError(f"requirements.txt missing in {release_dir}")
    proc = _run([str(_release_python()), "-m", "pip", "install", "-r", str(requirements)])
    if proc.returncode != 0:
        raise UpdateError(proc.stderr.strip() or proc.stdout.strip() or "pip install failed")


def _compile_release(release_dir: Path) -> None:
    python_files = [str(path) for path in release_dir.rglob("*.py") if ".venv" not in path.parts]
    if not python_files:
        raise UpdateError("No Python files found in release.")
    proc = _run([str(_release_python()), "-m", "py_compile", *python_files])
    if proc.returncode != 0:
        raise UpdateError(proc.stderr.strip() or proc.stdout.strip() or "py_compile failed")


def _clone_release(repo_url: str, ref: str) -> Path:
    release_dir = RELEASES_DIR / _release_name(ref)
    proc = _run(["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(release_dir)])
    if proc.returncode != 0:
        raise UpdateError(proc.stderr.strip() or proc.stdout.strip() or f"git clone failed for {ref}")
    return release_dir


def _write_metadata(release_dir: Path, ref: str, channel: str, source: str = "github") -> ReleaseMetadata:
    sha_proc = _run(["git", "-C", str(release_dir), "rev-parse", "--short", "HEAD"], check=False)
    git_sha = sha_proc.stdout.strip() if sha_proc.returncode == 0 else "unknown"
    metadata = ReleaseMetadata(
        version=ref,
        ref=ref,
        channel=channel,
        source=source,
        git_sha=git_sha,
        created_at=now_timestamp(),
    )
    write_release_metadata(release_dir, metadata)
    return metadata


def _safe_symlink(link: Path, target: Path | None) -> None:
    tmp_link = link.with_name(f".{link.name}.tmp")
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    if target is None:
        if link.exists() or link.is_symlink():
            link.unlink()
        return
    tmp_link.symlink_to(target)
    os.replace(tmp_link, link)


def _restart_services() -> None:
    for service in (PANEL_SERVICE, ADMIN_SERVICE):
        proc = _systemctl("restart", service)
        if proc.returncode != 0:
            raise UpdateError(proc.stderr.strip() or proc.stdout.strip() or f"Failed to restart {service}")


def _admin_healthcheck(timeout: float = 4.0) -> tuple[bool, str]:
    try:
        response = requests.get("http://127.0.0.1:8765/health", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return bool(payload.get("ok", False)), str(payload.get("status", "ok"))
        return True, "Admin healthcheck returned a non-object payload."
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else None
        return False, f"Admin healthcheck failed with HTTP {status if status is not None else 'error'}."
    except requests.Timeout:
        return False, "Admin healthcheck timed out."
    except requests.ConnectionError as exc:
        return False, f"Admin healthcheck connection error: {exc}"
    except requests.RequestException as exc:
        return False, f"Admin healthcheck failed: {exc}"
    except ValueError as exc:
        return False, f"Admin healthcheck returned invalid JSON: {exc}"


def _rollback_link(previous_release: Path) -> None:
    if not previous_release.exists():
        raise UpdateError(f"Rollback target missing: {previous_release}")
    _safe_symlink(CURRENT_LINK, previous_release)
    _restart_services()


def rollback_release(config_path: Path = CONFIG_FILE) -> UpdateOutcome:
    previous = current_release_dir()
    target = PREVIOUS_LINK.resolve(strict=False) if PREVIOUS_LINK.exists() or PREVIOUS_LINK.is_symlink() else None
    if target is None:
        raise UpdateError("No previous release available.")
    _safe_symlink(CURRENT_LINK, target)
    _restart_services()
    report = run_doctor(config_path)
    return UpdateOutcome(ok=report.ok, message="Rollback completed.", version=read_release_metadata(target).version if read_release_metadata(target) else None, release_dir=target, doctor=report)


def update_release(config: AppConfig | None = None, config_path: Path = CONFIG_FILE, on_boot: bool = False) -> UpdateOutcome:
    ensure_base_directories()
    config = config or load_config(config_path)
    if not config.updates.enabled:
        return UpdateOutcome(ok=False, message="Updates are disabled in config.")
    if on_boot and (not config.updates.check_on_boot or not config.updates.auto_update):
        return UpdateOutcome(ok=True, message="Boot update skipped by config.")

    repo_url = _repo_url(config.updates.github_repo)
    ref = latest_ref(config)
    release_dir = _clone_release(repo_url, ref)
    _write_metadata(release_dir, ref=ref, channel=config.updates.channel)
    _install_requirements(release_dir)
    _compile_release(release_dir)

    current = current_release_dir()
    if current is not None:
        _safe_symlink(PREVIOUS_LINK, current)
    _safe_symlink(CURRENT_LINK, release_dir)
    _restart_services()

    report = run_doctor(config_path)
    admin_ok, admin_detail = _admin_healthcheck()
    admin_report = DoctorReport(checks=list(report.checks))
    if report.ok and admin_ok:
        version = read_release_metadata(release_dir).version if read_release_metadata(release_dir) else ref
        message = "Update completed." if not on_boot else "Boot update completed."
        return UpdateOutcome(ok=True, message=message, version=version, release_dir=release_dir, doctor=admin_report)

    if config.updates.rollback_on_failed_healthcheck:
        if current is not None:
            _safe_symlink(CURRENT_LINK, current)
            _restart_services()
        reason = report.format_text()
        if not admin_ok:
            reason = f"{reason}\n{admin_detail}"
        raise UpdateError(f"Healthcheck failed after update; rollback executed.\n{reason}")

    version = read_release_metadata(release_dir).version if read_release_metadata(release_dir) else ref
    message = "Update completed." if not on_boot else "Boot update completed."
    return UpdateOutcome(ok=False, message=f"Update completed but checks failed: {admin_detail}", version=version, release_dir=release_dir, doctor=admin_report)


def list_installed_releases() -> list[dict[str, str]]:
    releases: list[dict[str, str]] = []
    if not RELEASES_DIR.exists():
        return releases
    current = current_release_dir()
    previous = PREVIOUS_LINK.resolve(strict=False) if PREVIOUS_LINK.exists() or PREVIOUS_LINK.is_symlink() else None
    for path in sorted((p for p in RELEASES_DIR.iterdir() if p.is_dir()), reverse=True):
        metadata = read_release_metadata(path)
        releases.append(
            {
                "name": path.name,
                "version": metadata.version if metadata else path.name,
                "current": str(path == current),
                "previous": str(path == previous),
            }
        )
    return releases
