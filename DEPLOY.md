# Деплой проекта на VPS

Инструкция полностью покрывает три задачи:
1. Обнулить локальную git-историю.
2. Залить код в новый репозиторий на новом GitHub-аккаунте.
3. Развернуть сайт на VPS `5.10.213.39` с HTTPS.

> Все команды на сервере — от `root` (или через `sudo`). Локальные команды — в каталоге проекта.

---

## 1. Обнуление git-истории и пуш в новый GitHub

### 1.1 На GitHub
1. Создайте/войдите в новый аккаунт.
2. **New repository** → имя, например `booksrecom` → **Private** → НЕ ставьте галочки `Add README/.gitignore/license` (репо должен быть пустым) → Create.
3. Settings → Developer settings (внизу слева) → **Personal access tokens → Fine-grained tokens** → Generate new token:
   - Repository access: Only select repositories → ваш `booksrecom`.
   - Permissions: **Contents — Read and write**.
   - Скопируйте токен (показывается один раз).

### 1.2 Локально (Windows, bash или PowerShell)
В корне проекта `C:\Users\c\Desktop\books_new`:

```bash
# Закрыть всё, что держит файлы (IDE, dev-server) — Windows иначе не даст удалить .git
rm -rf .git

# Перепроверьте, что в .gitignore уже игнорируются .env, *.zip, staticfiles/, media/, venv/
git init -b main
git add .
git status      # пробегите глазами — не должно быть .env, venv, *.zip, db.sqlite3
git commit -m "initial commit"

git remote add origin https://github.com/<НОВЫЙ_ЛОГИН>/booksrecom.git
git push -u origin main
# Логин: <НОВЫЙ_ЛОГИН>
# Пароль: вставьте PAT (фактически будет скрыт при вводе)
```

Если Git Credential Manager помнит старый аккаунт `qu1kzy`:
- Windows → «Учётные данные» (Credential Manager) → «Учётные данные Windows» → удалить запись `git:https://github.com`.
- Либо разово: `git config --local credential.helper "" && git push -u origin main`.

---

## 2. Подготовка VPS

```bash
ssh root@5.10.213.39

# Базовая защита
apt update && apt upgrade -y
apt install -y ufw git curl
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Docker + compose-плагин
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
docker --version && docker compose version
```

## 3. DNS

В панели регистратора домена создайте A-записи:

| Тип | Имя  | Значение     | TTL |
|-----|------|--------------|-----|
| A   | @    | 5.10.213.39  | 600 |
| A   | www  | 5.10.213.39  | 600 |

Подождите 5–60 минут и проверьте: `dig +short ваш-домен.tld` должен вернуть `5.10.213.39`.

## 4. Клон проекта

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/<НОВЫЙ_ЛОГИН>/booksrecom.git
cd booksrecom

cp .env.example .env
nano .env
```

В `.env` обязательно заменить:
- `SECRET_KEY` — сгенерируйте: `python3 -c "import secrets;print(secrets.token_urlsafe(64))"`
- `DEBUG=False`
- `ALLOWED_HOSTS=ваш-домен.tld,www.ваш-домен.tld,5.10.213.39`
- `SITE_URL=https://ваш-домен.tld`
- `CSRF_TRUSTED_ORIGINS=https://ваш-домен.tld,https://www.ваш-домен.tld`
- `POSTGRES_PASSWORD` и `DB_PASSWORD` — одинаковый сильный пароль
- `OPENROUTER_API_KEY`, `RECAPTCHA_*`, токены ботов — ваши значения

## 5. Выпуск SSL-сертификата

```bash
chmod +x init-letsencrypt.sh
DOMAIN=ваш-домен.tld EMAIL=kbbk0020@gmail.com bash init-letsencrypt.sh
```

Скрипт:
- подставит ваш домен в `nginx/default.conf`,
- скачает рекомендованные TLS-параметры,
- создаст временный самоподписанный сертификат,
- запустит nginx,
- получит реальный сертификат от Let's Encrypt через webroot,
- перезагрузит nginx.

Контейнер `certbot` потом будет автоматически продлевать сертификат каждые 12 часов.

## 6. Полный запуск

```bash
docker compose up -d --build
docker compose ps              # все сервисы должны быть Up (db — healthy)
docker compose logs -f web     # пока не убедитесь, что сайт стартанул, потом Ctrl+C

docker compose exec web python manage.py createsuperuser
```

Откройте `https://ваш-домен.tld` — сайт работает по HTTPS.

## 7. Дальнейшие обновления

На локальной машине:
```bash
git add -A && git commit -m "..." && git push
```
На сервере:
```bash
cd /opt/booksrecom
git pull
docker compose up -d --build
# Миграции применяются автоматически в команде web,
# но для подстраховки можно вручную:
docker compose exec web python manage.py migrate
```

## 8. Бэкап БД (рекомендую)

```bash
mkdir -p /opt/backups
cat >/etc/cron.daily/booksrecom-db <<'SH'
#!/bin/sh
cd /opt/booksrecom
docker compose exec -T db pg_dump -U postgres bookopolis | gzip > /opt/backups/db_$(date +\%F).sql.gz
find /opt/backups -name 'db_*.sql.gz' -mtime +14 -delete
SH
chmod +x /etc/cron.daily/booksrecom-db
```

---

## Чеклист проверки

- [ ] `git log` локально показывает один коммит `initial commit`.
- [ ] `git remote -v` указывает на новый репо нового аккаунта.
- [ ] `https://ваш-домен.tld` открывается, замок зелёный, http → https редирект.
- [ ] `https://ваш-домен.tld/admin/` логин работает, статика админки видна.
- [ ] WebSocket-чат (`ai_chat`): открыть DevTools → Network → WS, отправка сообщения проходит.
- [ ] `docker compose ps` — все Up, нет цикла рестартов.
- [ ] `docker compose logs --tail=200 web` — без 500-ок.
- [ ] `crontab -l` или `ls /etc/cron.daily/` показывает бэкап-задачу.
