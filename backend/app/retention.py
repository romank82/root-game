"""Retention 30 дней (Sprint DB-Audit-2).

Удаляет устаревшие нефинансовые runtime-записи старше 30 дней:

  - PlayerEvent        — лог действий игрока (13.3);
  - AppError           — ошибки приложения (13.4);
  - LocationProof      — подтверждения геолокации;
  - TeamSessionMessage — сообщения чата командных сессий.

Финансовые (WalletTransaction, GasTransaction, StarsPayment, PlayerTransfer,
WithdrawalRequest) и аудит (AdminAuditLog) НЕ удаляются — это immutable
ledger/история (см. AGENTS.md, «Финансовая целостность» и «Безопасность»).

Планировщик — APScheduler (BackgroundScheduler): cron-задача раз в день
в 03:00 (локальное время сервера). Логика очистки вынесена в отдельную
функцию cleanup_old_records(), чтобы её можно было тестировать без
поднятия планировщика.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import AppError, PlayerEvent
from app.geo_team_runtime_models import LocationProof, TeamSessionMessage

logger = logging.getLogger(__name__)

# Срок хранения: 30 дней.
RETENTION_DAYS = 30

# Таблицы, подлежащие очистке. Порядок важен только для читаемости лога.
# Вся очистка идёт в одной транзакции (SessionLocal.begin()).
_CLEANUP_TABLES = (
    PlayerEvent,
    AppError,
    LocationProof,
    TeamSessionMessage,
)


def _cutoff() -> datetime:
    """Граница очистки: записи строго старше этого момента удаляются."""
    return datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)


def cleanup_old_records() -> dict[str, int]:
    """Удалить записи старше RETENTION_DAYS из нефинансовых runtime-таблиц.

    Возвращает словарь {таблица: количество удалённых строк}. Работает в
    одной транзакции: если любая из DELETE падает — откатывается вся
    очистка (атомарность), исключение пробрасывается наружу.

    Финансовые таблицы и admin_audit_log здесь намеренно НЕ затронуты.
    """
    cutoff = _cutoff()
    deleted: dict[str, int] = {}

    with SessionLocal.begin() as session:
        for model in _CLEANUP_TABLES:
            result = session.execute(
                delete(model).where(model.created_at < cutoff)
            )
            count = result.rowcount or 0
            deleted[model.__tablename__] = count

    return deleted


def run_retention_job() -> None:
    """Один прогон очистки с логированием результата.

    Обёртка над cleanup_old_records(): ловит ошибки, чтобы падение
    очистки не обрушило поток планировщика.
    """
    try:
        deleted = cleanup_old_records()
    except Exception:  # noqa: BLE001 — job не должен ронять планировщик
        logger.exception("Retention cleanup failed")
        return

    total = sum(deleted.values())
    details = ", ".join(f"{name}={count}" for name, count in deleted.items())
    logger.info("Retention cleanup done: %d rows removed (%s)", total, details)


_scheduler: "BackgroundScheduler | None" = None


def start_scheduler() -> None:
    """Запустить фоновый планировщик (раз в день в 03:00).

    Идемпотентно: повторный вызов не создаёт второй планировщик.
    APScheduler импортируется лениво, чтобы тесты и импорт модуля не
    требовали пакет без необходимости.
    """
    global _scheduler

    if _scheduler is not None:
        logger.warning("Retention scheduler already running; skipping start")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(
        timezone="UTC",
        # Позволяет планировщику корректно завершаться вместе с процессом.
        daemon=True,
    )
    scheduler.add_job(
        run_retention_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="retention-cleanup",
        name="Retention 30d cleanup",
        replace_existing=True,
        # Не накапливать пропущенные запуски после долгого простоя.
        coalesce=True,
        misfire_grace_time=3600,
    )
    # Авто-откат просроченных батчей выплат (шаг 5 внешних выплат): забытый
    # батч держал бы деньги игроков в processing бесконечно.
    scheduler.add_job(
        run_payout_timeout_job,
        trigger=CronTrigger(hour="*/1", minute=15),
        id="payout-timeout-rollback",
        name="Payout batch processing timeout rollback",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=1800,
    )
    # Автоподтверждение выплат: сеть может показать перевод не сразу, а
    # админ не обязан помнить про кнопку «Сверить». Раз в 5 минут — часто
    # достаточно, чтобы подтвердить раньше таймаута отката (по умолчанию 24ч),
    # и редко достаточно, чтобы не долбить TON API.
    scheduler.add_job(
        run_payout_auto_confirm_job,
        trigger=CronTrigger(minute="*/5"),
        id="payout-auto-confirm",
        name="Payout auto-confirm delivered withdrawals",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Retention scheduler started (daily at 03:00 UTC)")


def run_payout_timeout_job() -> None:
    """Авто-откат батчей, которые висят в processing дольше таймаута.

    Ошибки не пробрасываем: падение джоба не должно ронять планировщик,
    а следующий запуск через час повторит попытку.
    """
    from app.payout_rollback_service import rollback_all_stale_batches

    try:
        rolled_back = rollback_all_stale_batches()
    except Exception:  # noqa: BLE001 — джоб не должен падать
        logger.exception("Payout timeout job failed")
        return
    if rolled_back:
        logger.warning(
            "Payout timeout job: откачено батчей — %d", len(rolled_back)
        )



def run_payout_auto_confirm_job() -> None:
    """Автоподтверждение открытых батчей выплат (CMS-тумблер).

    Зачем: после подписи в Tonkeeper заявка остаётся processing, пока админ
    не нажмёт «Сверить». Если сеть показала перевод не сразу, а админ забыл
    вернуться — заявка откатывается по таймауту, хотя деньги уже у игрока.

    Тумблер ton.payout_auto_confirm_enabled (default true) выключает джоб
    целиком: тогда подтверждение снова только вручную.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SystemSetting
    from app.payout_confirm_service import auto_confirm_open_batches

    try:
        with SessionLocal() as session:
            setting = session.scalar(
                select(SystemSetting).where(
                    SystemSetting.key == "ton.payout_auto_confirm_enabled",
                    SystemSetting.status == "active",
                )
            )
            enabled = (
                setting.value_json
                if setting is not None and isinstance(setting.value_json, bool)
                else True
            )
        if not enabled:
            return
        results = auto_confirm_open_batches()
    except Exception:  # noqa: BLE001 — джоб не должен ронять планировщик
        logger.exception("Payout auto-confirm job failed")
        return

    changed = [item for item in results if item.get("confirmedCount")]
    if changed:
        logger.info(
            "Payout auto-confirm: обработано батчей %d, подтверждено %d",
            len(results),
            sum(int(item.get("confirmedCount") or 0) for item in changed),
        )

def stop_scheduler() -> None:
    """Остановить планировщик (вызывается при shutdown)."""
    global _scheduler

    if _scheduler is None:
        return

    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Retention scheduler stopped")
