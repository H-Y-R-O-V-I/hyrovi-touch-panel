from __future__ import annotations

import os
import tempfile
from pathlib import Path
from grp import getgrnam
from pwd import getpwnam
from typing import Any

import yaml


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def atomic_write_yaml(
    target: Path,
    data: Any,
    *,
    owner: str = "root",
    group: str = "hyrovi-panel",
    mode: int = 0o640,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dump_yaml(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.chown(tmp_name, getpwnam(owner).pw_uid, getgrnam(group).gr_gid)
        os.replace(tmp_name, target)
        dir_fd = os.open(str(target.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except FileNotFoundError:
            pass
