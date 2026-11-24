#!/usr/bin/env bash
# Installs and starts this repository in place on Amazon Linux 2023.
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root: sudo bash deploy/setup.sh" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${APP_DIR}/.env"

read -r -p "RDS PostgreSQL endpoint: " RDS_ENDPOINT
read -r -p "Database name [commerce]: " DB_NAME
DB_NAME="${DB_NAME:-commerce}"
read -r -p "Database user [commerce_user]: " DB_USER
DB_USER="${DB_USER:-commerce_user}"
read -r -s -p "Database password: " DB_PASSWORD
echo

if [[ -z "${RDS_ENDPOINT}" || -z "${DB_PASSWORD}" ]]; then
  echo "RDS endpoint and database password are required." >&2
  exit 1
fi

dnf update -y
dnf install -y python3 python3-pip nginx

ENCODED_PASSWORD="$(DB_PASSWORD="${DB_PASSWORD}" python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))')"
SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

umask 077
printf 'DATABASE_URL=postgresql+psycopg://%s:%s@%s:5432/%s\nSECRET_KEY=%s\nFLASK_ENV=production\n' \
  "${DB_USER}" "${ENCODED_PASSWORD}" "${RDS_ENDPOINT}" "${DB_NAME}" "${SECRET_KEY}" > "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

cd "${APP_DIR}"
"${APP_DIR}/.venv/bin/flask" --app app init-db

sed "s|__APP_DIR__|${APP_DIR}|g" "${APP_DIR}/deploy/commerce.service" > /etc/systemd/system/commerce.service
install -m 644 "${APP_DIR}/deploy/nginx.conf" /etc/nginx/conf.d/commerce.conf
nginx -t
systemctl daemon-reload
systemctl enable --now commerce nginx

echo "Deployment complete. Open: http://$(curl -fsS http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')/"
