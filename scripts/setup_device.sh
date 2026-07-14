#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run this setup script with sudo."
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"
INSTALL_ROOT="/opt/hyrovi-touch-panel"
RELEASES_DIR="${INSTALL_ROOT}/releases"
CURRENT_LINK="${INSTALL_ROOT}/current"
PREVIOUS_LINK="${INSTALL_ROOT}/previous"
SHARED_DIR="${INSTALL_ROOT}/shared"
VENV_DIR="${INSTALL_ROOT}/venv"
CONFIG_DIR="/etc/hyrovi-touch-panel"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
STATE_DIR="/var/lib/hyrovi-touch-panel"
LOG_DIR="/var/log/hyrovi-touch-panel"
CACHE_DIR="/var/cache/hyrovi-touch-panel/pycache"
USER_NAME="hyrovi-panel"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
GIT_SHA="$(git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo local)"
RELEASE_NAME="${TIMESTAMP}-${GIT_SHA}"
RELEASE_DIR="${RELEASES_DIR}/${RELEASE_NAME}"

apt-get update
apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-pygame \
  python3-yaml \
  git \
  curl \
  jq \
  unclutter \
  evtest \
  libinput-tools \
  libegl1 \
  libegl-mesa0 \
  libgles2 \
  rsync

if ! id -u "${USER_NAME}" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "${STATE_DIR}" --create-home --shell /usr/sbin/nologin "${USER_NAME}"
fi
usermod -a -G video,render,input,systemd-journal,tty,audio "${USER_NAME}" || true

install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0755 "${INSTALL_ROOT}" "${RELEASES_DIR}" "${SHARED_DIR}" "${STATE_DIR}"
install -d -o root -g "${USER_NAME}" -m 0750 "${CONFIG_DIR}"
install -d -o root -g root -m 0755 "${LOG_DIR}"
install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0755 "${CACHE_DIR}"

mkdir -p "${RELEASE_DIR}"
rsync -a \
  --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude '*.sqlite3' \
  --exclude '*.db' \
  --exclude '.env' \
  --exclude 'token.json' \
  --exclude 'cookies.sqlite' \
  --exclude 'state' \
  "${REPO_DIR}/" "${RELEASE_DIR}/"

chown -R "${USER_NAME}:${USER_NAME}" "${RELEASE_DIR}"

python3 - <<PY
from pathlib import Path
from app.runtime import ReleaseMetadata, write_release_metadata

release_dir = Path("${RELEASE_DIR}")
write_release_metadata(
    release_dir,
    ReleaseMetadata(
        version="${RELEASE_NAME}",
        ref="${RELEASE_NAME}",
        channel="stable",
        source="setup",
        git_sha="$(git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)",
        created_at="${TIMESTAMP}",
    ),
)
PY

if [ -L "${CURRENT_LINK}" ] || [ -e "${CURRENT_LINK}" ]; then
  OLD_TARGET="$(readlink -f "${CURRENT_LINK}" || true)"
  if [ -n "${OLD_TARGET}" ] && [ -e "${OLD_TARGET}" ]; then
    ln -sfn "${OLD_TARGET}" "${PREVIOUS_LINK}"
  fi
fi
ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${RELEASE_DIR}/requirements.txt"

if [ ! -f "${CONFIG_FILE}" ]; then
  install -m 0640 -o root -g "${USER_NAME}" "${RELEASE_DIR}/config.example.yaml" "${CONFIG_FILE}"
fi

BOOT_CONFIG=""
if [ -f /boot/firmware/config.txt ]; then
  BOOT_CONFIG="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
  BOOT_CONFIG="/boot/config.txt"
fi

if [ -n "${BOOT_CONFIG}" ]; then
  cp -a "${BOOT_CONFIG}" "${BOOT_CONFIG}.bak.hyrovi-${TIMESTAMP}"
  python3 - <<PY
from pathlib import Path

path = Path("${BOOT_CONFIG}")
text = path.read_text(encoding="utf-8")
start = "# BEGIN HYROVI TOUCH PANEL"
end = "# END HYROVI TOUCH PANEL"
block = """# BEGIN HYROVI TOUCH PANEL
# Keep HDMI enabled and prepare the fixed 800x480 touch panel.
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=800 480 60 6 0 0 0
disable_overscan=1
# END HYROVI TOUCH PANEL
"""
if start in text and end in text:
    before = text.split(start, 1)[0].rstrip()
    after = text.split(end, 1)[1].lstrip("\n")
    new_text = before + "\n" + block + after
else:
    if not text.endswith("\n"):
        text += "\n"
    new_text = text + "\n" + block
path.write_text(new_text, encoding="utf-8")
PY
fi

CMDLINE_FILE=""
if [ -f /boot/firmware/cmdline.txt ]; then
  CMDLINE_FILE="/boot/firmware/cmdline.txt"
elif [ -f /boot/cmdline.txt ]; then
  CMDLINE_FILE="/boot/cmdline.txt"
fi

if [ -n "${CMDLINE_FILE}" ]; then
  cp -a "${CMDLINE_FILE}" "${CMDLINE_FILE}.bak.hyrovi-${TIMESTAMP}"
  python3 - <<PY
from pathlib import Path

path = Path("${CMDLINE_FILE}")
text = path.read_text(encoding="utf-8").strip()
if "consoleblank=0" not in text:
    text = text + " consoleblank=0"
path.write_text(text + "\n", encoding="utf-8")
PY
fi

install -m 0755 "${REPO_DIR}/scripts/hyrovi-panel" /usr/local/bin/hyrovi-panel
install -m 0755 "${REPO_DIR}/scripts/doctor.sh" /usr/local/bin/hyrovi-panel-doctor
install -m 0755 "${REPO_DIR}/scripts/hyrovi-touch-config-save" /usr/local/bin/hyrovi-touch-config-save

install -m 0644 "${REPO_DIR}/systemd/hyrovi-touch-panel.service" /etc/systemd/system/hyrovi-touch-panel.service
install -m 0644 "${REPO_DIR}/systemd/hyrovi-touch-admin.service" /etc/systemd/system/hyrovi-touch-admin.service
install -m 0644 "${REPO_DIR}/systemd/hyrovi-touch-update-on-boot.service" /etc/systemd/system/hyrovi-touch-update-on-boot.service

cat >/etc/sudoers.d/hyrovi-touch-panel <<'SUDOERS'
hyrovi-panel ALL=(root) NOPASSWD: ALL
SUDOERS
chmod 0440 /etc/sudoers.d/hyrovi-touch-panel

systemctl daemon-reload
systemctl enable hyrovi-touch-panel.service
systemctl enable hyrovi-touch-admin.service
systemctl enable hyrovi-touch-update-on-boot.service
systemctl disable --now getty@tty1.service || true
systemctl mask getty@tty1.service || true
systemctl restart hyrovi-touch-panel.service || true
systemctl restart hyrovi-touch-admin.service || true

echo "Setup complete."
echo "Config: ${CONFIG_FILE}"
echo "Current release: ${CURRENT_LINK}"
