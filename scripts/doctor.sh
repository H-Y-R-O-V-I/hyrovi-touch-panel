#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -x "/opt/hyrovi-touch-panel/venv/bin/python" ]; then
  PYTHON_BIN="/opt/hyrovi-touch-panel/venv/bin/python"
elif [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

cd "${ROOT_DIR}"
if [ -f /etc/hyrovi-touch-panel/config.yaml ]; then
  exec "${PYTHON_BIN}" -m app.cli --config /etc/hyrovi-touch-panel/config.yaml doctor "$@"
fi

exec "${PYTHON_BIN}" -m app.cli --config config.example.yaml doctor "$@"
