#!/usr/bin/env bash
# ============================================================
# راه‌اندازی یکجا روی VPS اوبونتو 22.04/24.04 (به‌عنوان root)
# استفاده:  sudo bash setup_vps.sh   (بعد از کپی پروژه به /opt/dahom)
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dahom}"
DOMAIN="${DOMAIN:-}"   # مثل dahom.example.com — اگر خالی بود فقط http

echo "==> به‌روزرسانی سیستم"
apt-get update -y && apt-get upgrade -y

echo "==> نصب پکیج‌ها"
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

echo "==> ساخت کاربر سرویس"
id -u dahom &>/dev/null || useradd -r -s /usr/sbin/nologin dahom

echo "==> ساخت محیط مجازی و نصب کتابخانه‌ها"
cd "$APP_DIR"
if [ ! -d venv ]; then python3 -m venv venv; fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r requirements.txt

echo "==> ساخت .env اگر نیست"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" "$APP_DIR/.env"
  echo "    .env ساخته شد — رمز ADMIN_PASSWORD و SECRET_KEY را بررسی کنید"
fi

echo "==> مالکیت"
chown -R dahom:dahom "$APP_DIR"

echo "==> systemd"
cp "$APP_DIR/deploy/dahom.service" /etc/systemd/system/dahom.service
systemctl daemon-reload
systemctl enable --now dahom

echo "==> nginx"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/dahom
ln -sf /etc/nginx/sites-available/dahom /etc/nginx/sites-enabled/dahom
if [ -f /etc/nginx/sites-enabled/default ]; then rm -f /etc/nginx/sites-enabled/default; fi
if [ -n "$DOMAIN" ]; then
  sed -i "s/dahom.example.com/$DOMAIN/g" /etc/nginx/sites-available/dahom
fi
nginx -t && systemctl reload nginx

if [ -n "$DOMAIN" ]; then
  echo "==> SSL با Let's Encrypt"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@"$DOMAIN" --redirect || true
fi

echo "======================================================"
echo "تمام شد!"
echo "  سایت: http://$DOMAIN  (یا IP سرور)"
echo "  پنل:  /panel  (رمز: در فایل $APP_DIR/.env)"
echo "  لاگ:  journalctl -u dahom -f"
echo "======================================================"
