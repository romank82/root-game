from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, Item, KeyRules

router = APIRouter(prefix="/api/v1/admin/key-rules", tags=["admin-key-rules"])

KEY_RULES_READ_PERMISSION = "key_rules.read"
KEY_RULES_MANAGE_PERMISSION = "key_rules.manage"


class KeyRuleCreatePayload(BaseModel):
    item_id: str = Field(min_length=1, max_length=64)
    is_consumable: bool = True
    stack_limit: int = Field(default=1, ge=1, le=100_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    transfer_forbidden: bool = True
    sale_forbidden: bool = True
    trade_forbidden: bool = True


class KeyRuleUpdatePayload(BaseModel):
    is_consumable: bool | None = None
    stack_limit: int | None = Field(default=None, ge=1, le=100_000)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    transfer_forbidden: bool | None = None
    sale_forbidden: bool | None = None
    trade_forbidden: bool | None = None


class CreateKeyItemPayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=128)
    symbol: str | None = Field(default=None, max_length=32)
    description: str | None = None
    rarity: str = Field(default="common", max_length=32)
    is_consumable: bool = True
    stack_limit: int = Field(default=1, ge=1, le=100_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    transfer_forbidden: bool = True
    sale_forbidden: bool = True
    trade_forbidden: bool = True


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _validate_item_is_key(session: Session, item_id: str) -> Item:
    item = session.get(Item, item_id)

    if item is None:
        raise HTTPException(
            status_code=422,
            detail="Указанный item_id не существует.",
        )

    if item.category.upper() != "KEY":
        raise HTTPException(
            status_code=422,
            detail="Правила ключей можно создавать только для Item с category=KEY.",
        )

    return item


def _ensure_no_existing_rule(
    session: Session,
    item_id: str,
    exclude_rule_id: str | None = None,
) -> None:
    statement = select(KeyRules.id).where(KeyRules.item_id == item_id)

    if exclude_rule_id is not None:
        statement = statement.where(KeyRules.id != exclude_rule_id)

    if session.scalar(statement) is not None:
        raise HTTPException(
            status_code=409,
            detail="Для этого Item правила ключей уже существуют.",
        )


def _serialize_key_rule(rule: KeyRules, item: Item) -> dict[str, Any]:
    return {
        "id": rule.id,
        "itemId": rule.item_id,
        "isConsumable": rule.is_consumable,
        "stackLimit": rule.stack_limit,
        "sortOrder": rule.sort_order,
        "transferForbidden": rule.transfer_forbidden,
        "saleForbidden": rule.sale_forbidden,
        "tradeForbidden": rule.trade_forbidden,
        "itemTitle": item.title,
        "itemCode": item.code,
        "itemSymbol": item.symbol,
        "itemStatus": item.status,
        "createdAt": rule.created_at.isoformat() if rule.created_at else None,
        "updatedAt": rule.updated_at.isoformat() if rule.updated_at else None,
    }


@router.get("")
def list_admin_key_rules(
    item_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(KEY_RULES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        statement = (
            select(KeyRules, Item)
            .join(Item, Item.id == KeyRules.item_id)
            .order_by(KeyRules.sort_order, KeyRules.id)
        )

        if item_id is not None:
            statement = statement.where(KeyRules.item_id == item_id)

        rows = session.execute(statement).all()

        return {
            "keyRules": [_serialize_key_rule(rule, item) for rule, item in rows]
        }


@router.get("/items")
def list_admin_key_items(
    status: str | None = None,
    _actor: AdminUser = Depends(require_permission(KEY_RULES_READ_PERMISSION)),
):
    """Список items с category=KEY для выбора в миссии.

    Отдаёт только id, code, title, symbol, status — минимально
    необходимое для dropdown. Сортировка: title.
    Query: status='published' (default) | 'draft' | 'archived' | 'all'.
    """
    with SessionLocal.begin() as session:
        statement = select(Item).where(Item.category == "KEY")

        if status is None:
            status = "published"

        if status != "all":
            statement = statement.where(Item.status == status)

        statement = statement.order_by(Item.title)

        items = session.scalars(statement).all()

        return {
            "items": [
                {
                    "id": item.id,
                    "code": item.code,
                    "title": item.title,
                    "symbol": item.symbol,
                    "status": item.status,
                }
                for item in items
            ]
        }


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_admin_key_item(
    payload: CreateKeyItemPayload,
    request: Request,
    actor: AdminUser = Depends(require_permission(KEY_RULES_MANAGE_PERMISSION)),
):
    """Создать новый ключ: Item(category=KEY) + KeyRules одним запросом.

    code должен быть уникален (в таблице items).
    id генерируется как f"item-{uuid4.hex[:16]}".
    slug = code.lower().replace('_','-') для читаемости.
    """
    with SessionLocal.begin() as session:
        if session.scalar(select(Item.id).where(Item.code == payload.code)):
            raise HTTPException(
                status_code=409,
                detail="Item с таким code уже существует.",
            )

        item = Item(
            id=f"item-{uuid4().hex[:16]}",
            slug=payload.code.lower().replace("_", "-"),
            code=payload.code,
            title=payload.title,
            description=payload.description,
            symbol=payload.symbol,
            category="KEY",
            rarity=payload.rarity,
            status="published",
            is_unique=True,
            content={},
        )
        session.add(item)
        session.flush()

        rule = KeyRules(
            id=_new_id("key-rule"),
            item_id=item.id,
            is_consumable=payload.is_consumable,
            stack_limit=payload.stack_limit,
            sort_order=payload.sort_order,
            transfer_forbidden=payload.transfer_forbidden,
            sale_forbidden=payload.sale_forbidden,
            trade_forbidden=payload.trade_forbidden,
        )
        session.add(rule)
        session.flush()

        write_admin_audit(
            session,
            actor=actor,
            action="key_item.created",
            entity_type="key_rule",
            entity_id=rule.id,
            request=request,
            permission_code=KEY_RULES_MANAGE_PERMISSION,
            metadata={
                "itemId": item.id,
                "itemCode": item.code,
                "itemTitle": item.title,
                "isConsumable": rule.is_consumable,
                "stackLimit": rule.stack_limit,
                "sortOrder": rule.sort_order,
                "transferForbidden": rule.transfer_forbidden,
                "saleForbidden": rule.sale_forbidden,
                "tradeForbidden": rule.trade_forbidden,
            },
        )

        return {"keyRule": _serialize_key_rule(rule, item)}


@router.get("/{key_rule_id}")
def get_admin_key_rule(
    key_rule_id: str,
    _admin: AdminUser = Depends(require_permission(KEY_RULES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        rule = session.get(KeyRules, key_rule_id)

        if rule is None:
            raise HTTPException(status_code=404, detail="Правила ключа не найдены.")

        item = session.get(Item, rule.item_id)

        return {"keyRule": _serialize_key_rule(rule, item)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_key_rule(
    payload: KeyRuleCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(KEY_RULES_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        item = _validate_item_is_key(session, payload.item_id)
        _ensure_no_existing_rule(session, item_id=payload.item_id)

        rule = KeyRules(
            id=_new_id("key-rule"),
            item_id=payload.item_id,
            is_consumable=payload.is_consumable,
            stack_limit=payload.stack_limit,
            sort_order=payload.sort_order,
            transfer_forbidden=payload.transfer_forbidden,
            sale_forbidden=payload.sale_forbidden,
            trade_forbidden=payload.trade_forbidden,
        )
        session.add(rule)
        session.flush()

        write_admin_audit(
            session,
            actor=admin,
            action="key_rule.created",
            entity_type="key_rule",
            entity_id=rule.id,
            request=request,
            permission_code=KEY_RULES_MANAGE_PERMISSION,
            metadata={
                "itemId": rule.item_id,
                "isConsumable": rule.is_consumable,
                "stackLimit": rule.stack_limit,
                "sortOrder": rule.sort_order,
                "transferForbidden": rule.transfer_forbidden,
                "saleForbidden": rule.sale_forbidden,
                "tradeForbidden": rule.trade_forbidden,
            },
        )

        return {"keyRule": _serialize_key_rule(rule, item)}


@router.patch("/{key_rule_id}")
def update_admin_key_rule(
    key_rule_id: str,
    payload: KeyRuleUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(KEY_RULES_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        rule = session.get(KeyRules, key_rule_id)

        if rule is None:
            raise HTTPException(status_code=404, detail="Правила ключа не найдены.")

        changed_fields: list[str] = []

        scalar_fields = {
            "is_consumable": "isConsumable",
            "stack_limit": "stackLimit",
            "sort_order": "sortOrder",
            "transfer_forbidden": "transferForbidden",
            "sale_forbidden": "saleForbidden",
            "trade_forbidden": "tradeForbidden",
        }

        for field_name, audit_name in scalar_fields.items():
            if field_name in updates:
                setattr(rule, field_name, updates[field_name])
                changed_fields.append(audit_name)

        session.flush()

        write_admin_audit(
            session,
            actor=admin,
            action="key_rule.updated",
            entity_type="key_rule",
            entity_id=rule.id,
            request=request,
            permission_code=KEY_RULES_MANAGE_PERMISSION,
            metadata={
                "itemId": rule.item_id,
                "changedFields": changed_fields,
            },
        )

        item = session.get(Item, rule.item_id)

        return {"keyRule": _serialize_key_rule(rule, item)}
