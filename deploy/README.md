# Deploy ROOT Game (production)

Пошаговая инструкция переноса на VPS (Ubuntu 22.04/24.04).

## 1. Подготовка сервера

```bash
# Ubuntu 22.04+, пользователь deployer (не root)
sudo adduser deployer
sudo usermod -aG sudo deployer

# Пакеты
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip \
  nginx postgresql postgresql-contrib \
  certbot python3-certbot-nginx git

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
cd /opt/root-game && npm ci && VITE_API_BASE_URL=/api npm run build
# dist/ → /opt/root-game/frontend/dist (см. nginx root)
```

## 7. systemd

```bash
sudo cp /opt/root-game/deploy/root-game.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now root-game
sudo systemctl status root-game
```

## 8. nginx + HTTPS

```bash
sudo cp /opt/root-game/deploy/nginx.conf /etc/nginx/sites-available/root-game
sudo ln -s /etc/nginx/sites-available/root-game /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Домен: A-запись → IP сервера. Подождать распространение DNS.
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

## 9. Telegram webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://your-domain.com/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

## 10. Проверка

```bash
curl https://your-domain.com/health   # → OK
# Открыть Mini App в Telegram
sudo journalctl -u root-game -f       # логи
```

## Обновление

```bash
cd /opt/root-game && git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart root-game
cd .. && npm ci && VITE_API_BASE_URL=/api npm run build
sudo systemctl reload nginx
```