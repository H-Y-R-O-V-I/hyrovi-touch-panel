#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
if [ -n "${PYTHON_BIN:-}" ]; then
  SELECTED_PYTHON="${PYTHON_BIN}"
else
  SELECTED_PYTHON=""
  for candidate in python3.11 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      SELECTED_PYTHON="${candidate}"
      break
    fi
  done
fi

cd "${ROOT_DIR}"

if [ -z "${SELECTED_PYTHON}" ]; then
  echo "No suitable Python interpreter was found."
  exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
  "${SELECTED_PYTHON}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r requirements.txt

echo "Development environment is ready."
