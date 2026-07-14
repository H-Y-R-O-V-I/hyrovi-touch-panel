#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "/opt/hyrovi-touch-panel/venv/bin/python" ]; then
  VENV_PYTHON="/opt/hyrovi-touch-panel/venv/bin/python"
else
  VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
fi

if [ ! -x "${VENV_PYTHON}" ]; then
  echo "Virtual environment not found."
  exit 1
fi

cd "${ROOT_DIR}"
if [ -f /etc/hyrovi-touch-panel/config.yaml ]; then
  exec "${VENV_PYTHON}" app.py --config /etc/hyrovi-touch-panel/config.yaml "$@"
fi

exec "${VENV_PYTHON}" app.py --config config.example.yaml "$@"
