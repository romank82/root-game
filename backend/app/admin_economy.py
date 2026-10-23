"""Admin economy endpoints (Этап 9.1 + 9.2, чтение).

1) GET /audit (9.1) — сверка балансов кошельков: для каждого Wallet
   SUM(credit.amount) - SUM(debit.amount) == available_balance.
   Расхождения возвращаются админу целиком; в admin_audit пишется
   только sample (до 10), чтобы не раздувать metadata_json.
2) GET /transactions (9.2) — реестр всех операций ROOT с фильтрами
   (player_id, type, from, to) и пагинацией (limit/offset). Индексы для
   фильтров — миграция ec7a5b3f1984.

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
from app.models import AdminUser, GamePlayer, Wallet, WalletTransaction

router = APIRouter(prefix="/api/v1/admin/economy", tags=["admin-economy"])

ECONOMY_READ_PERMISSION = "economy.read"


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