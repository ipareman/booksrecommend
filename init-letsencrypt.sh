#!/bin/bash
# Первичная инициализация Let's Encrypt для проекта.
# Использование: DOMAIN=your-domain.tld EMAIL=you@mail.com bash init-letsencrypt.sh
#
# Скрипт создаёт самоподписанный "dummy"-сертификат, запускает nginx, выпускает
# настоящий сертификат через webroot-плагин certbot, заменяет dummy и перечитывает nginx.

set -e

if ! command -v docker >/dev/null; then
  echo "Docker не найден"; exit 1
fi

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "Передайте DOMAIN и EMAIL: DOMAIN=example.com EMAIL=you@mail.com bash init-letsencrypt.sh"
  exit 1
fi

DATA_PATH="./certbot"
RSA_KEY_SIZE=4096

# Подставляем домен в nginx-конфиг (плейсхолдер DOMAIN_PLACEHOLDER -> реальный домен)
sed -i "s/DOMAIN_PLACEHOLDER/${DOMAIN}/g" nginx/default.conf

# Скачиваем рекомендованные параметры Let's Encrypt
mkdir -p "$DATA_PATH/conf"
if [ ! -e "$DATA_PATH/conf/options-ssl-nginx.conf" ] || [ ! -e "$DATA_PATH/conf/ssl-dhparams.pem" ]; then
  echo "### Скачиваю TLS-параметры ..."
  curl -fsSL https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$DATA_PATH/conf/options-ssl-nginx.conf"
  curl -fsSL https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$DATA_PATH/conf/ssl-dhparams.pem"
fi

# Создаём фиктивный сертификат, чтобы nginx стартовал
echo "### Создаю dummy-сертификат для $DOMAIN ..."
LIVE_PATH="/etc/letsencrypt/live/$DOMAIN"
mkdir -p "$DATA_PATH/conf/live/$DOMAIN"
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$RSA_KEY_SIZE -days 1 \
    -keyout '$LIVE_PATH/privkey.pem' \
    -out    '$LIVE_PATH/fullchain.pem' \
    -subj   '/CN=localhost'" certbot

echo "### Поднимаю nginx ..."
docker compose up -d nginx

echo "### Удаляю dummy-сертификат ..."
docker compose run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN \
         /etc/letsencrypt/archive/$DOMAIN \
         /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "### Запрашиваю настоящий сертификат у Let's Encrypt ..."
docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $EMAIL --agree-tos --no-eff-email \
    -d $DOMAIN -d www.$DOMAIN \
    --rsa-key-size $RSA_KEY_SIZE --force-renewal" certbot

echo "### Перезагружаю nginx ..."
docker compose exec nginx nginx -s reload

echo "Готово. Поднимите остальные сервисы: docker compose up -d --build"
