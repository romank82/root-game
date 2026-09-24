# Архитектура CHIMERA

## Текущее состояние
- Frontend: React + TypeScript + Vite, исходники в `src/`.
- Backend: FastAPI 0.116.1, Python 3.13, SQLAlchemy 2.
- БД: PostgreSQL 17; миграции Alembic.
- Docker Compose: `frontend`, `backend`, `db`.
- Текущий Alembic head: `d19f7a3e8b62`.

## Реализовано
Telegram WebApp auth, игровой content engine, player progress, inventory,
ROOT wallets/transactions, admin auth, super-admin, permissions, audit,
admin mission API и admin management API.

## Инварианты
PostgreSQL — источник истины. Схема меняется только Alembic-миграциями.
Секреты не попадают в git, документацию, БД или frontend bundle.
Связанный с историей контент в целевой модели архивируется, а не удаляется.
System settings contract: `docs/system-settings.md`.
