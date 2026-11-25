#!/bin/sh
# backup-db.sh — ежедневный дамп PostgreSQL и чистка старых копий.
#
# Запускается systemd-таймером root-game-backup.timer (см. deploy/).
# Требования: pg_dump (postgresql-client), доступ к БД под тем же
# пользователем, что в DATABASE_URL.
#
# Использование:
#   sh deploy/backup-db.sh
#
# Переменные окружения (необязательные):
#   BACKUP_DIR  — каталог для дампов (по умолчанию /var/backups/root-game)
#   KEEP_DAYS   — сколько дней хранить (по умолчанию 14)
#
# Копия пишется атомарно: сначала во временный файл, потом mv. Прерванный
# дамп не оставит «битый» файл, который потом примут за нормальный.
set -eu

APP_ROOT="${APP_ROOT:-/opt/root-game}"
ENV_FILE="${ENV_FILE:-$APP_ROOT/backend/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/root-game}"
KEEP_DAYS="${KEEP_DAYS:-14}"

log() { printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }
die() { log "ОШИБКА: $1"; exit 1; }

# --- 1. Настройки окружения ---------------------------------------------------
test -r "$ENV_FILE" || die "нет доступа к $ENV_FILE"
command -v pg_dump >/dev/null 2>&1 || die "не найден pg_dump (apt install postgresql-client)"

# DATABASE_URL вида postgresql+psycopg://user:pass@host:port/dbname
DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"'')
[ -n "$DB_URL" ] || die "DATABASE_URL не задан в $ENV_FILE"

case "$DB_URL" in
    postgresql*) ;;
    *) die "DATABASE_URL не PostgreSQL ($DB_URL) — дамп не поддерживается" ;;
esac

# Убираем SQLAlchemy-префикс драйвера: pg_dump его не понимает.
PG_URL=$(printf '%s' "$DB_URL" | sed 's|^postgresql+[a-z0-9_]*://|postgresql://|')

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP=$(date -u +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/rootgame_$STAMP.dump"
TMP="$OUT.part"

# --- 2. Дамп ------------------------------------------------------------------
# Старые недописанные .part от прерванных запусков — мусор, чистим.
find "$BACKUP_DIR" -maxdepth 1 -name "rootgame_*.dump.part" -mtime +1 -delete 2>/dev/null || true

log "дамп в $OUT"
# --no-password: если пароль не задан в URL/.pgpass, pg_dump должен упасть
# сразу, а не висеть на интерактивном вводе (в systemd ввода нет вовсе).
# PGCONNECT_TIMEOUT: не ждать недоступный сервер бесконечно.
if ! PGCONNECT_TIMEOUT=30 pg_dump --no-password --format=custom \
        --no-owner --no-privileges --dbname="$PG_URL" > "$TMP"; then
    rm -f "$TMP"
    die "pg_dump завершился с ошибкой"
fi

# Проверка, что дамп читается: pg_restore --list ловит обрезанный файл.
if command -v pg_restore >/dev/null 2>&1; then
    if ! pg_restore --list "$TMP" >/dev/null 2>&1; then
        rm -f "$TMP"
        die "дамп повреждён (pg_restore --list не читает)"
    fi
fi

SIZE=$(du -h "$TMP" | cut -f1)
mv "$TMP" "$OUT"
chmod 600 "$OUT"
log "готово: $OUT ($SIZE)"

# --- 3. Чистка старых копий ---------------------------------------------------
REMOVED=0
for old in "$BACKUP_DIR"/rootgame_*.dump; do
    [ -e "$old" ] || continue
    case "$old" in *.part) continue ;; esac
    if [ -n "$(find "$old" -maxdepth 0 -mtime "+$KEEP_DAYS" 2>/dev/null)" ]; then
        rm -f "$old"
        REMOVED=$((REMOVED + 1))
    fi
done
log "удалено старых копий: $REMOVED (хранение $KEEP_DAYS дней)"

# --- 4. Контроль свободного места ---------------------------------------------
AVAIL=$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print int($4/1024)}')
if [ "$AVAIL" -lt 512 ]; then
    log "ВНИМАНИЕ: на разделе с бэкапами меньше 512 МБ свободно (${AVAIL} МБ)"
fi

log "успешно завершено"
