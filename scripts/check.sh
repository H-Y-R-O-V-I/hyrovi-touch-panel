#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

cd "${ROOT_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not available."
  exit 1
fi

if [ ! -x "${VENV_PYTHON}" ]; then
  echo "Virtual environment is missing at ${ROOT_DIR}/.venv."
  exit 1
fi

"${VENV_PYTHON}" - <<'PY'
import importlib

for module_name in ("pygame", "yaml"):
    importlib.import_module(module_name)
print("Requirements import check passed.")
PY

"${VENV_PYTHON}" -m py_compile app.py $(find app -name '*.py' -type f | sort)

echo "Syntax and import checks passed."

