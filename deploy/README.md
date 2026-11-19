# Deploy ROOT Game (production)

Пошаговая инструкция переноса на VPS (Ubuntu 22.04/24.04).

## 0. Обновление уже работающего сервера

```bash
cd /opt/root-game
git pull
SITE_URL=https://himeraprotocol.pro sh deploy/deploy.sh
```

Скрипт делает всё сам: бэкап текущей сборки, `npm run build`, выкладку в
каталог, который отдаёт nginx, `pip install`, `alembic upgrade head`,
перезапуск `root-game` и поллера депозитов, проверку `health` и сверку
бандла, который реально отдаёт nginx.

Если `SITE_URL` не задан, проверка выдачи nginx пропускается.

## 1. Подготовка сервера

```bash
# Ubuntu 22.04+, пользователь deployer (не root)
sudo adduser deployer
sudo usermod -aG sudo deployer

# Пакеты
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip \
  nginx postgresql postgresql-contrib \
  certbot python3-certbot-nginx git curl

# Node.js 20.x (нужен для сборки фронтенда)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Firewall
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## 2. PostgreSQL

```bash
sudo -u postgres createuser rootgame -P   # задать пароль
sudo -u postgres createdb rootgame -O rootgame
```

## 3. Код

```bash
sudo mkdir -p /opt/root-game && sudo chown deployer:deployer /opt/root-game
git clone <repo> /opt/root-game
cd /opt/root-game/backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. .env

```bash
cp /opt/root-game/deploy/.env.production.example /opt/root-game/backend/.env
# Заполнить:
#   TELEGRAM_WEBHOOK_SECRET  — длинная случайная строка
#   GAME_SESSION_SECRET      — длинная случайная строка
#   DATABASE_URL             — пароль от PostgreSQL
#   TELEGRAM_BOT_TOKEN       — токен бота из @BotFather
#   TELEGRAM_BOT_USERNAME    — username бота
#   TON_*                    — при необходимости
#   SENTRY_DSN               — при использовании Sentry/GlitchTip
chmod 600 /opt/root-game/backend/.env
```

## 5. Миграции

```bash
cd /opt/root-game/backend && source venv/bin/activate
alembic upgrade head
```

## 6. Frontend

```bash
cd /opt/root-game
npm ci
npm run build
```

> ⚠️ `VITE_API_BASE_URL` задавать НЕЛЬЗЯ: все пути в коде уже содержат `/api`
> (`/api/v1/...`). Если задать `VITE_API_BASE_URL=/api` — получится двойной
> `/api` (`/api/api/v1/...`) и 404.

> ⚠️ `npm run build` кладёт сборку в `/opt/root-game/dist`, а nginx отдаёт
> `/opt/root-game/frontend/dist`. Копировать вручную не нужно — это делает
> `deploy/deploy.sh` (шаг 4). При ручной выкладке:
> `mkdir -p frontend/dist && cp -a dist/. frontend/dist/`

## 7. systemd

```bash
sudo cp /opt/root-game/deploy/root-game.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now root-game
sudo systemctl status root-game

# Поллер депозитов ROOT-jetton — отдельный процесс, не внутри gunicorn
sudo cp /opt/root-game/deploy/root-game-deposit-poller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now root-game-deposit-poller
```

## 8. nginx + HTTPS

```bash
sudo cp /opt/root-game/deploy/nginx.conf /etc/nginx/sites-available/root-game
# заменить your-domain.com на реальный домен
sudo sed -i 's/your-domain\.com/himeraprotocol.pro/g' \
  /etc/nginx/sites-available/root-game
sudo ln -sf /etc/nginx/sites-available/root-game /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# Домен: A-запись → IP сервера. Подождать распространение DNS.
sudo certbot --nginx -d himeraprotocol.pro -d www.himeraprotocol.pro
```

> ⚠️ На nginx 1.24 (Ubuntu 24.04) HTTP/2 включается параметром
> `listen 443 ssl http2`, а не директивой `http2 on` — она появилась в
> 1.25.1 и на 1.24 даёт `unknown directive "http2"`.

## 9. Telegram webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://himeraprotocol.pro/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

## 10. Проверка

```bash
curl https://himeraprotocol.pro/health   # → OK
# Открыть Mini App в Telegram
sudo journalctl -u root-game -f          # логи
```

Проверить, что отдаётся актуальный бандл:

```bash
curl -s https://himeraprotocol.pro/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js'
ls -la /opt/root-game/frontend/dist/assets/
# имена должны совпадать
```

## Обновление

```bash
cd /opt/root-game && git pull
SITE_URL=https://himeraprotocol.pro sh deploy/deploy.sh
```

## Бэкап

```bash
pg_dump -U rootgame rootgame | gzip > /opt/backups/rootgame_$(date +%F).sql.gz
find /opt/backups -name 'rootgame_*.sql.gz' -mtime +7 -delete
```
