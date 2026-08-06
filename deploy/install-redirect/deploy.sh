#!/bin/bash
# Deploys d.magicboxie.com to the shared nginx host. The HTTPS vhost redirects
# every request to the public raw GitHub installer. It follows the same
# bootstrap-vhost -> Certbot webroot -> HTTPS-vhost flow as pocketproducer-web.
# Safe to re-run.
set -euo pipefail

SSH_TARGET="deploy@104.131.183.186"
DOMAIN="d.magicboxie.com"
CERTBOT_EMAIL="simplex0@gmail.com"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CERTBOT_CMD="sudo -n /usr/bin/certbot certonly --webroot -w /var/www/certbot -d $DOMAIN --non-interactive --agree-tos -m $CERTBOT_EMAIL"

install_vhost() {
  local src="$1"
  local filename
  filename=$(basename "$src")

  scp "$src" "$SSH_TARGET:/tmp/$filename"
  ssh "$SSH_TARGET" "sudo -n /bin/cp '/tmp/$filename' '/etc/nginx/sites-available/$DOMAIN' && sudo -n /bin/ln -sf '/etc/nginx/sites-available/$DOMAIN' '/etc/nginx/sites-enabled/$DOMAIN' && sudo -n /usr/sbin/nginx -t && sudo -n /bin/systemctl reload nginx"
}

if ssh "$SSH_TARGET" "sudo -n /usr/bin/test -f '/etc/letsencrypt/live/$DOMAIN/cert.pem'"; then
  echo "==> Certificate already exists"
else
  echo "==> Installing HTTP bootstrap vhost"
  install_vhost "$SCRIPT_DIR/server/sites-available/$DOMAIN.bootstrap.conf"

  echo "==> Requesting TLS certificate"
  ssh "$SSH_TARGET" "$CERTBOT_CMD"
fi

echo "==> Installing HTTPS redirect vhost"
install_vhost "$SCRIPT_DIR/server/sites-available/$DOMAIN.conf"

echo "==> Renewing certificate if due"
ssh "$SSH_TARGET" "$CERTBOT_CMD"
ssh "$SSH_TARGET" "sudo -n /bin/systemctl reload nginx"

echo "Done. https://$DOMAIN redirects to the MagicBoxie installer."
