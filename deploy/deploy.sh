#!/bin/sh
# deploy.sh — сборка и выкладка ROOT Game на VPS.
#
# Запуск на сервере из каталога репозитория (/opt/root-game):
#   sh deploy/deploy.sh
#
# Скрипт идемпотентен: повторный запуск безопасен.
# Требует прав на запись в APP_ROOT и прав на перезапуск сервисов
# (запускать под deployer, sudo только для systemctl/nginx).
set -eu

APP_ROOT="${APP_ROOT:-/opt/root-game}"
FRONTEND_ROOT="${FRONTEND_ROOT:-$APP_ROOT/frontend/dist}"
VENV="$APP_ROOT/backend/venv"
SERVICE_ROOT="root-game"
SERVICE_POLLER="root-game-deposit-poller"

step() { printf '\n=== %s ===\n' "$1"; }

step "1/7 Проверка окружения"
cd "$APP_ROOT"
test -d .git || { echo "ОШИБКА: $APP_ROOT не git-репозиторий"; exit 1; }
test -d node_modules || { echo "ОШИБКА: нет node_modules, выполните npm ci"; exit 1; }
test -x "$VENV/bin/python" || { echo "ОШИБКА: нет venv в $VENV"; exit 1; }
echo "репозиторий : $APP_ROOT"
echo "фронт dist  : $FRONTEND_ROOT"
echo "venv        : $VENV"

step "2/7 Резервная копия собранного фронта"
if [ -d "$FRONTEND_ROOT" ]; then
    BACKUP="$FRONTEND_ROOT.bak_$(date +%Y%m%d_%H%M%S)"
    cp -a "$FRONTEND_ROOT" "$BACKUP"
    echo "бэкап: $BACKUP"
else
    echo "предыдущей сборки нет — пропускаем"
fi

step "3/7 Сборка фронтенда"
# VITE_API_BASE_URL НЕ задаём: пути в коде уже содержат /api.
npm run build
test -f dist/index.html || { echo "ОШИБКА: dist/index.html не создан"; exit 1; }
BUILT_ASSET="$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' dist/index.html | head -1)"
echo "собран бандл: $BUILT_ASSET"

step "4/7 Выкладка фронтенда в $FRONTEND_ROOT"
# Копируем содержимое, затем удаляем ассеты, которых нет в новой сборке,
# чтобы каталог не разрастался старыми бандлами.
mkdir -p "$FRONTEND_ROOT"
cp -a dist/. "$FRONTEND_ROOT"/
# Удаляем старые хешированные бандлы: имя нового уже есть в index.html,
# всё остальное в assets/index-* — мусор от прошлых сборок.
NEW_ASSET_NAME="$(basename "$BUILT_ASSET")"
find "$FRONTEND_ROOT/assets" -maxdepth 1 -type f -name 'index-*' 2>/dev/null | while read -r old; do
    if [ "$(basename "$old")" != "$NEW_ASSET_NAME" ]; then
        rm -f "$old"
    fi
done
DEPLOYED_ASSET="$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' "$FRONTEND_ROOT/index.html" | head -1)"
if [ "$DEPLOYED_ASSET" != "$BUILT_ASSET" ]; then
    echo "ОШИБКА: index.html указывает на $DEPLOYED_ASSET, ожидался $BUILT_ASSET"
    exit 1
fi
echo "выложено: $DEPLOYED_ASSET"

step "5/7 Миграции и зависимости бэкенда"
"$VENV/bin/pip" install -q -r backend/requirements.txt
cd "$APP_ROOT/backend" && "$VENV/bin/alembic" upgrade head
cd "$APP_ROOT"

step "6/7 Перезапуск сервисов"
sudo systemctl restart "$SERVICE_ROOT"
if systemctl list-unit-files | grep -q "^$SERVICE_POLLER"; then
    sudo systemctl restart "$SERVICE_POLLER" || echo "ВНИМАНИЕ: поллер депозитов не перезапустился"
else
    echo "юнит $SERVICE_POLLER не установлен — пропускаем"
fi

step "7/7 Проверка"
sleep 2
sudo systemctl is-active "$SERVICE_ROOT" >/dev/null \
    && echo "сервис $SERVICE_ROOT: active" \
    || { echo "ОШИБКА: $SERVICE_ROOT не active"; sudo systemctl status "$SERVICE_ROOT" --no-pager | tail -20; exit 1; }

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8001/health}"
if curl -fsS --max-time 10 "$HEALTH_URL" >/dev/null; then
    echo "health: OK ($HEALTH_URL)"
else
    echo "ОШИБКА: health не отвечает ($HEALTH_URL)"
    exit 1
fi

# Проверяем, что nginx отдаёт именно новый бандл.
SITE_URL="${SITE_URL:-}"
if [ -n "$SITE_URL" ]; then
    SERVED="$(curl -fsS --max-time 10 "$SITE_URL/" | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1)"
    if [ "$SERVED" = "$BUILT_ASSET" ]; then
        echo "nginx отдаёт: $SERVED (совпадает)"
    else
        echo "ОШИБКА: nginx отдаёт $SERVED, ожидался $BUILT_ASSET"
        echo "проверьте root в /etc/nginx/sites-available/root-game"
        exit 1
    fi
else
    echo "SITE_URL не задан — проверка выдачи nginx пропущена"
    echo "для полной проверки: SITE_URL=https://himeraprotocol.pro sh deploy/deploy.sh"
fi

printf '\n=== ГОТОВО: %s ===\n' "$BUILT_ASSET"
