#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "/opt/hyrovi-touch-panel/venv/bin/python" ]; then
  VENV_PYTHON="/opt/hyrovi-touch-panel/venv/bin/python"
elif [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
  VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
else
  VENV_PYTHON="$(command -v python3)"
fi

cd "${ROOT_DIR}"

for script in scripts/*.sh; do
  bash -n "${script}"
done
bash -n scripts/hyrovi-panel

python3 - <<'PY'
from pathlib import Path

requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
expected = {"Flask", "PyYAML", "pygame", "requests"}
found = {line.split("==")[0].split(">=")[0].split("<")[0] for line in requirements if line and not line.startswith("#")}
missing = sorted(expected - found)
if missing:
    raise SystemExit(f"Missing requirements: {', '.join(missing)}")
print("Requirements file check passed.")
PY

"${VENV_PYTHON}" -m py_compile app.py admin/server.py $(find app -name '*.py' -type f | sort)

for service in systemd/*.service; do
  systemd-analyze verify "${service}" >/dev/null 2>&1 || true
done

grep -q "sudo ./scripts/setup_device.sh" README.md
grep -q "hyrovi-panel status" README.md

echo "Syntax and import checks passed."
