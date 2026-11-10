"""Admin economy endpoints (Этап 9.1 + 9.2, чтение).

1) GET /audit (9.1) — сверка балансов кошельков: для каждого Wallet
   SUM(credit.amount) - SUM(debit.amount) == available_balance.
   Расхождения возвращаются админу целиком; в admin_audit пишется
   только sample (до 10), чтобы не раздувать metadata_json.
2) GET /transactions (9.2) — реестр всех операций ROOT с фильтрами
   (player_id, type, from, to) и пагинацией (limit/offset). Индексы для
   фильтров — миграция ec7a5b3f1984.
3) GET /stars-payments (Sprint 12.2) — журнал Stars-платежей (покупка газа,
   10.4) с фильтрами (status, player_id, search, from, to) и пагинацией.
   Только чтение: StarsPayment пишет исключительно stars_service.

Право: economy.read (сид-миграция f4c2e8a1d9b6, append-only).
Ядро (модели, ledger, движок) не трогаем — только чтение.
Логика: WalletTransaction.amount всегда >= 0, направление
задаёт transaction_type ("credit"/"debit"); status у проводок нет
(все финальные). balance_after — снимок, не источник.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, or_, select

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.datetime_utils import ensure_utc
from app.db import SessionLocal
from app.models import (
    AdminUser,
    GamePlayer,
    StarsPayment,
    Wallet,
    WalletTransaction,
)

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT (как в admin_player_wallet).
NANO_PER_ROOT = 100_000_000

router = APIRouter(prefix="/api/v1/admin/economy", tags=["admin-economy"])

ECONOMY_READ_PERMISSION = "economy.read"

# Статусы stars_payments: те же, что в CHECK-constraint модели
# (ck_stars_payments_status). Значения заданы схемой БД, не CMS.
STARS_PAYMENT_STATUSES = ("pending", "completed", "refunded")


@router.get("/audit")
def audit_balances(
    request: Request,
    admin: AdminUser = Depends(require_permission(ECONOMY_READ_PERMISSION)),
) -> dict:
    """Сверка ledger-балансов: SUM(credit) - SUM(debit) == available_balance.

    Возвращает все кошельки с расхождениями (mismatches) и признак ok.
    При наличии расхождений пишет запись в admin_audit (sample <= 10).
    """
    with SessionLocal.begin() as session:
        credit_sum = func.sum(
            case(
                (WalletTransaction.transaction_type == "credit", WalletTransaction.amount),
                else_=0,
            )
        )
        debit_sum = func.sum(
            case(
                (WalletTransaction.transaction_type == "debit", WalletTransaction.amount),
                else_=0,
            )
        )

        # 1) Ledger-сумма по каждому кошельку (у кошельков без проводок её нет).
        ledger_rows = session.execute(
            select(
                WalletTransaction.wallet_id,
                (credit_sum - debit_sum).label("ledger_sum"),
            ).group_by(WalletTransaction.wallet_id)
        ).all()
        ledger = {
            wallet_id: int(ledger_sum or 0) for wallet_id, ledger_sum in ledger_rows
        }

        # 2) Все кошельки и сравнение.
        wallets = session.scalars(select(Wallet)).all()
        mismatches = []
        for wallet in wallets:
            expected = ledger.get(wallet.id, 0)
            actual = int(wallet.available_balance)
            if expected != actual:
                mismatches.append(
                    {
                        "walletId": wallet.id,
                        "playerId": wallet.player_id,
                        "expected": expected,
                        "actual": actual,
                        "difference": actual - expected,
                    }
                )

        # 3) Audit — только при расхождениях (sample <= 10).
        if mismatches:
            write_admin_audit(
                session,
                actor=admin,
                action="economy.audit",
                entity_type="economy",
                entity_id=None,
                request=request,
                permission_code=ECONOMY_READ_PERMISSION,
                metadata={
                    "count": len(mismatches),
                    "total": len(wallets),
                    "sample": mismatches[:10],
                },
            )

        return {
            "ok": len(mismatches) == 0,
            "total": len(wallets),
            "mismatches": mismatches,
        }


@router.get("/transactions")
def list_economy_transactions(
    player_id: str | None = None,
    type: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: AdminUser = Depends(require_permission(ECONOMY_READ_PERMISSION)),
) -> dict:
    """Реестр операций ROOT (все проводки) с фильтрами и пагинацией.

    Фильтры:
      - player_id — транзакции конкретного игрока (join через Wallet);
      - search — поиск по подстроке display_name (LIKE case-sensitive:
        «Роман» найдёт «Роман», но не «роман») ИЛИ по точному player_id;
        display_name не уникален — вернутся все совпавшие;
      - type — только "credit" или "debit" (иначе 422);
      - from/to — диапазон created_at, ISO 8601 (иначе 422);
      - limit (1..200) / offset — пагинация.
    metadata_json в ответ не включён: реестру нужны только базовые поля.
    """
    with SessionLocal.begin() as session:
        query = (
            select(WalletTransaction, Wallet.player_id, GamePlayer.display_name)
            .join(Wallet, Wallet.id == WalletTransaction.wallet_id)
            .join(GamePlayer, GamePlayer.id == Wallet.player_id)
        )

        # ORM relationship() на Wallet/WalletTransaction нет — join вручную.
        if player_id:
            query = query.where(Wallet.player_id == player_id)

        if search:
            search_value = search.strip()
            if search_value:
                query = query.where(
                    or_(
                        Wallet.player_id == search_value,
                        GamePlayer.display_name.like(f"%{search_value}%"),
                    )
                )

        if type is not None:
            if type not in ("credit", "debit"):
                raise HTTPException(
                    status_code=422,
                    detail="type должен быть credit или debit.",
                )
            query = query.where(WalletTransaction.transaction_type == type)

        if from_ is not None:
            try:
                from_datetime = ensure_utc(datetime.fromisoformat(from_))
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="Некорректная дата в параметре from.",
                )
            query = query.where(WalletTransaction.created_at >= from_datetime)

        if to is not None:
            try:
                to_datetime = ensure_utc(datetime.fromisoformat(to))
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="Некорректная дата в параметре to.",
                )
            query = query.where(WalletTransaction.created_at <= to_datetime)

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        total = session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        rows = session.execute(
            query.order_by(
                WalletTransaction.created_at.desc(),
                WalletTransaction.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()

        transactions = [
            {
                "id": tx.id,
                "walletId": tx.wallet_id,
                "playerId": player_row_id,
                "playerDisplayName": display_name,
                "amount": tx.amount,
                "balanceAfter": tx.balance_after,
                # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
                "balanceAfterNano": (
                    getattr(tx, "balance_after_nano", None)
                    if getattr(tx, "balance_after_nano", None) is not None
                    else tx.balance_after * NANO_PER_ROOT
                ),
                "transactionType": tx.transaction_type,
                "reason": tx.reason,
                "referenceType": tx.reference_type,
                "referenceId": tx.reference_id,
                "createdAt": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx, player_row_id, display_name in rows
        ]

        return {
            "transactions": transactions,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def _parse_iso_datetime(value: str, param_name: str) -> datetime:
    """Разбор ISO 8601-строки фильтра (from/to) -> aware-UTC.

    Тот же разбор, что инлайн в list_economy_transactions, вынесен в хелпер:
    журнал Stars принимает два таких параметра. Некорректная строка -> 422.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Некорректная дата в параметре {param_name}.",
        ) from None
    # ensure_utc(None) вернул бы None, но fromisoformat всегда даёт datetime.
    return ensure_utc(parsed)


def _serialize_stars_payment(
    payment: StarsPayment, player_display_name: str | None = None
) -> dict:
    """StarsPayment -> безопасный JSON журнала (Sprint 12.2).

    payload — это reference_id инвойса, telegram_payment_charge_id —
    идентификатор платежа Telegram (nullable до successful_payment). Оба не
    секреты и нужны админу для сверки с инвойсом. gas_amount — Numeric(18,4):
    str() сохраняет точность без float-конверсий (как в stars_service).

    player_display_name — из JOIN с GamePlayer (Sprint 12.2-enhance): админ
    должен видеть, чей это платёж, особенно при поиске по нику. Nullable:
    у части игроков display_name не заполнен.
    """
    return {
        "id": payment.id,
        "playerId": payment.player_id,
        "playerDisplayName": player_display_name,
        "gasAmount": str(payment.gas_amount),
        "amountStars": payment.amount_stars,
        "status": payment.status,
        "telegramPaymentChargeId": payment.telegram_payment_charge_id,
        "referenceId": payment.reference_id,
        "payload": payment.payload,
        "createdAt": (
            ensure_utc(payment.created_at).isoformat() if payment.created_at else None
        ),
    }


@router.get("/stars-payments")
def list_stars_payments(
    status: str | None = None,
    player_id: str | None = None,
    player_search: str | None = None,
    search: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: AdminUser = Depends(require_permission(ECONOMY_READ_PERMISSION)),
) -> dict:
    """Журнал Stars-платежей (Sprint 12.2) — только чтение, без мутаций.

    Одна запись stars_payments = один инвойс (10.4-g-1). Фильтры:
      - status — pending|completed|refunded (иначе 422; CHECK модели);
      - player_id — точное совпадение;
      - player_search — id ИЛИ подстрока display_name / telegram_username /
        telegram_first_name / nickname_lower (ILIKE; набор полей как в
        GET /admin/players); id тоже матчится точно внутри этого фильтра;
      - search — подстрока reference_id / telegram_payment_charge_id /
        payload (ILIKE: регистронезависимо в PostgreSQL и SQLite);
      - from/to — диапазон created_at, ISO 8601 (иначе 422);
      - limit (1..200) / offset — пагинация, как в /transactions.
    Порядок — created_at desc, id desc (свежие платежи первыми).
    Запись StarsPayment делает только stars_service (инвойс/webhook).
    В ответе есть playerDisplayName (JOIN с GamePlayer; NULL, если у игрока
    display_name не заполнен).
    """
    with SessionLocal() as session:  # read-only, не begin()
        # JOIN с GamePlayer — всегда, а не только при player_search:
        # display_name нужен в ответе для каждой строки (playerDisplayName).
        # INNER JOIN безопасен: stars_payments.player_id NOT NULL + FK
        # RESTRICT -> строка всегда находит игрока, дублей нет (join по PK).
        query = select(StarsPayment, GamePlayer.display_name).join(
            GamePlayer, GamePlayer.id == StarsPayment.player_id
        )

        if status is not None:
            if status not in STARS_PAYMENT_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail="status должен быть pending, completed или refunded.",
                )
            query = query.where(StarsPayment.status == status)

        if player_id:
            query = query.where(StarsPayment.player_id == player_id)

        # Sprint 12.2-enhance: поиск по игроку — id ИЛИ ник/имя.
        # Набор полей и ILIKE — как в list_admin_players (GET /admin/players);
        # nickname_lower — lowercase-копия (латиница), поэтому value.lower().
        if player_search:
            player_value = player_search.strip()
            # Sprint 12.2-enhance: @ — стандартный префикс Telegram-username,
            # в БД хранится без @. Срезаем, чтобы @roman находил roman.
            player_value = player_value.removeprefix("@")
            if player_value:
                player_pattern = f"%{player_value}%"
                query = query.where(
                    or_(
                        StarsPayment.player_id == player_value,
                        GamePlayer.display_name.ilike(player_pattern),
                        GamePlayer.telegram_username.ilike(player_pattern),
                        GamePlayer.telegram_first_name.ilike(player_pattern),
                        GamePlayer.nickname_lower.ilike(f"%{player_value.lower()}%"),
                    )
                )

        if search:
            search_value = search.strip()
            if search_value:
                pattern = f"%{search_value}%"
                query = query.where(
                    or_(
                        StarsPayment.reference_id.ilike(pattern),
                        StarsPayment.telegram_payment_charge_id.ilike(pattern),
                        StarsPayment.payload.ilike(pattern),
                    )
                )

        if from_ is not None:
            query = query.where(
                StarsPayment.created_at >= _parse_iso_datetime(from_, "from")
            )

        if to is not None:
            query = query.where(StarsPayment.created_at <= _parse_iso_datetime(to, "to"))

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        total = session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        rows = session.execute(
            query.order_by(
                StarsPayment.created_at.desc(),
                StarsPayment.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()

        return {
            "items": [
                _serialize_stars_payment(payment, display_name)
                for payment, display_name in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
