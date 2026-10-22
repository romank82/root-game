"""Admin economy audit endpoint (Этап 9.1, часть 1).

Сверка балансов кошельков: для каждого Wallet
SUM(credit.amount) - SUM(debit.amount) == available_balance.
Расхождения возвращаются админу целиком; в admin_audit пишется
только sample (до 10), чтобы не раздувать metadata_json.

Право: economy.read (сид-миграция f4c2e8a1d9b6, append-only).
Ядро (модели, ledger, движок) не трогаем — только чтение.
Логика сверки: WalletTransaction.amount всегда >= 0, направление
задаёт transaction_type ("credit"/"debit"); status у проводок нет
(все финальные). balance_after — снимок, не источник.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, Wallet, WalletTransaction

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