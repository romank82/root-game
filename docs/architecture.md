# Архитектура CHIMERA

## Текущее состояние
- Frontend: React + TypeScript + Vite, исходники в `src/`.
- Backend: FastAPI 0.116.1, Python 3.13, SQLAlchemy 2.
- БД: PostgreSQL 17; миграции Alembic.
- Docker Compose: `frontend`, `backend`, `db`.
- Текущий Alembic head: `2f7a9c4e6d81`.

## Реализовано
Telegram WebApp auth, игровой content engine, player progress, inventory,
ROOT wallets/transactions, admin auth, super-admin, permissions, audit,
admin mission API и admin management API.
Применена geo/team runtime schema foundation: 10 runtime tables, immutable inventory events и reservation/history constraints. Geo/team API и domain executors ещё не реализованы.

## Инварианты
PostgreSQL — источник истины. Схема меняется только Alembic-миграциями.
Секреты не попадают в git, документацию, БД или frontend bundle.
Связанный с историей контент в целевой модели архивируется, а не удаляется.
System settings contract: `docs/system-settings.md`.
Public Segment/Mission content contract: `docs/segment-content-contract.md`.
Geo/team/cipher runtime contract: `docs/geo-team-mission-contract.md`.
