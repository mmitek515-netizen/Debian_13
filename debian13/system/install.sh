#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root (for example: sudo ./install.sh)." >&2
  exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
  echo "Python 3 is required. Install it with: apt-get install python3" >&2
  exit 1
fi

if ! getent group debian13 >/dev/null 2>&1; then
  addgroup --system debian13
fi
if ! getent passwd debian13 >/dev/null 2>&1; then
  adduser --system --ingroup debian13 --home /var/lib/debian13 \
    --no-create-home --shell /usr/sbin/nologin debian13
fi

install -d -o root -g root -m 0755 /usr/local/lib/debian13/system
install -o root -g root -m 0644 "$SOURCE_DIR/server.py" /usr/local/lib/debian13/system/server.py
install -d -o debian13 -g debian13 -m 0750 /var/lib/debian13/workspace
install -d -o root -g debian13 -m 0750 /etc/debian13

if [ ! -e /etc/debian13/system.env ]; then
  token=$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')
  umask 027
  {
    printf 'DEBIAN13_API_TOKEN=%s\n' "$token"
    printf 'MODEL_CHAT_URL=\nMODEL_API_KEY=\nMODEL_NAME=\n'
  } > /etc/debian13/system.env
  chown root:debian13 /etc/debian13/system.env
  chmod 0640 /etc/debian13/system.env
fi

install -o root -g root -m 0644 "$SOURCE_DIR/systemd/debian13-system.service" \
  /etc/systemd/system/debian13-system.service
systemctl daemon-reload
systemctl enable --now debian13-system.service

echo "Debian 13 system service installed and started."
echo "Local API: http://127.0.0.1:8080"
echo "To retrieve the generated local API token securely: sudo sed -n 's/^DEBIAN13_API_TOKEN=//p' /etc/debian13/system.env"
