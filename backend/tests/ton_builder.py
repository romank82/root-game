"""Сборка V5-сообщения РОВНО как у настоящего кошелька.

Эталон — реальный BOC от Tonkeeper (tests/fixtures_ton.py). Структура,
подтверждённая дампом:

  внешнее сообщение (ext_in):
    bits : 0b10 + src(addr_none или адрес) + import_fee + Either(1)
    refs : [тело]

  тело (подписанное):
    bits : op(32)=0x7369676e + wallet_id(32) + valid_until(32) + seqno(32)
           + Either(1)   <- 130 бит
           + подпись(512)
    refs : [первый узел списка действий]

  узел списка действий (OutList):
    bits : op(32)=0x0ec3c86d + send_mode(8)
    refs : [prev, message]

    prev — предыдущий узел или ПУСТАЯ ячейка (конец списка).

Прежние тестовые конструкторы складывали action отдельной ячейкой в ref и
не вставляли Either-бит в тело — поэтому они не воспроизводили реальное
сообщение и не ловили ошибку в разборе.
"""
from __future__ import annotations

import base64

from nacl.signing import SigningKey
from pytoniq_core import (
    Address,
    Cell,
    InternalMsgInfo,
    MessageAny,
    begin_cell,
)
from pytoniq_core.tlb.block import CurrencyCollection

JETTON = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"
SENDER = "kQAqDpRYGNJLa4AqlgoLdTZK9FwCdS0xX0cwSur8LuTRzz_9"
VALID_UNTIL = 1795538094
SEQNO = 7
WALLET_ID = 2147483645

ACTION_SEND_MSG = 0x0EC3C86D
WALLET_V5_SIGNED_OP = 0x7369676E
JETTON_TRANSFER_OP = 0xF8A7EA5


def transfer_message(
    query_id: int,
    amount_nano: int,
    recipient: str = JETTON,
    body_op: int = JETTON_TRANSFER_OP,
) -> MessageAny:
    """Внутреннее сообщение на jetton-wallet с телом TEP-74."""
    if body_op == JETTON_TRANSFER_OP:
        body = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(query_id, 64)
            .store_coins(amount_nano)
            .store_address(Address(recipient))
            .store_address(None)
            .store_bit(0)
            .store_coins(0)
            .store_bit(0)
            .end_cell()
        )
    else:
        body = begin_cell().store_uint(body_op, 32).store_string("hi").end_cell()

    return MessageAny(
        info=InternalMsgInfo(
            ihr_disabled=True,
            bounce=True,
            bounced=False,
            src=None,  # у внутренних сообщений в подписи src пуст
            dest=Address(JETTON),
            value=CurrencyCollection(grams=50_000_000),
            ihr_fee=0,
            fwd_fee=0,
            created_lt=0,
            created_at=0,
        ),
        init=None,
        body=body,
    )


def build_out_list(messages: list[MessageAny]) -> Cell:
    """Связный список действий: узел = op+mode в битах, [prev, message] в refs."""
    node: Cell = Cell.empty()  # конец списка
    for message in messages:
        node = (
            begin_cell()
            .store_uint(ACTION_SEND_MSG, 32)
            .store_uint(3, 8)  # send_mode
            .store_ref(node)  # prev
            .store_ref(message.serialize())
            .end_cell()
        )
    return node


def build_signed_body(messages: list[MessageAny], private_key: bytes) -> Cell:
    """Подписанное V5-тело ровно 642 бита, как в реальном BOC с прода.

    Раскладка (подтверждена дампом):
      op(32) + wallet_id(32) + valid_until(32) + seqno(32) = 128
      + 2 бита Either-выравнивания                        = 130
      + подпись(512)                                      = 642

    Два бита после полей — это «флаги/остаток» тела: в реальном сообщении
    первые 130 бит уходят под подпись целиком, поэтому здесь важно
    воспроизвести ту же длину, иначе срез подписи съедет на 1-2 бита.
    """
    actions = build_out_list(messages)
    signing = (
        begin_cell()
        .store_uint(WALLET_V5_SIGNED_OP, 32)
        .store_uint(WALLET_ID, 32)
        .store_uint(VALID_UNTIL, 32)
        .store_uint(SEQNO, 32)
        .store_bit(1)   # Either: действия в ref
        .store_ref(actions)
        .store_bit(0)   # выравнивание: ровно 130 бит до подписи
        .end_cell()
    )
    signature = SigningKey(private_key[:32]).sign(signing.hash).signature
    return (
        begin_cell()
        .store_bits(signing.bits)
        .store_ref(actions)
        .store_bytes(signature)
        .end_cell()
    )


def build_external(
    messages: list[MessageAny], private_key: bytes, with_src: bool = False
) -> str:
    """Внешнее сообщение в base64, как его возвращает TON Connect."""
    body = build_signed_body(messages, private_key)
    # Собираем внешнее сообщение штатным pytoniq: он знает раскладку
    # ext_in_msg_info (src, dest, import_fee) и кладёт тело в ref.
    from pytoniq import WalletV5R1

    message = WalletV5R1.create_external_msg(
        src=Address(SENDER) if with_src else None,
        dest=Address(SENDER),
        import_fee=0,
        body=body,
    )
    return base64.b64encode(message.serialize().to_boc()).decode()


def build_bare(messages: list[MessageAny], private_key: bytes) -> str:
    """Голое подписанное тело без внешней обёртки (проверка обратной совместимости)."""
    body = build_signed_body(messages, private_key)
    return base64.b64encode(body.to_boc()).decode()


def new_keypair() -> tuple[bytes, bytes]:
    from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_to_wallet_key

    public_key, private_key = mnemonic_to_wallet_key(mnemonic_new(24))
    return public_key, private_key
