"""Разбор подписанного TON Connect BOC и проверка подписи кошелька.

TON Connect возвращает base64 BOC — внешнее сообщение кошелька с подписью.
Внутри body: seqno + список WalletMessage, в каждом — внутреннее сообщение на
jetton-wallet с телом TEP-74 transfer (OP 0xf8a7ea5), где лежат query_id,
сумма и получатель.

Две задачи модуля:
  1. parse_signed_boc — вытащить список jetton-переводов из BOC.
  2. verify_wallet_signature — убедиться, что BOC подписан ожидаемым
     кошельком (ed25519 через pynacl). Без этого админ мог бы отправить
     произвольный BOC, и сервер подтвердил бы неоплаченные заявки.

Ограничения pytoniq 0.1.43: WalletMessage.deserialize — заглушка (`pass`),
поэтому send_mode и ref сообщения читаем сами.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pytoniq_core import Address, Cell, MessageAny, begin_cell

logger = logging.getLogger(__name__)

# OP-код transfer у Jetton wallet (TEP-74) — см. ton_service.JETTON_TRANSFER_OP.
JETTON_TRANSFER_OP = 0xF8A7EA5

# Wallet V4/V5: op=1 означает «отправить список сообщений».
WALLET_SEND_MESSAGES_OP = 1

# Максимум переводов в одном BOC: защита от гигантских payload'ов.
MAX_MESSAGES_PER_BOC = 255

# Длина подписи ed25519 в битах: внешнее сообщение кошелька начинается с неё.
SIGNATURE_BITS = 512

# Минимум бит после подписи: wallet_id(32)+valid_until(32)+seqno(32)+op(8).
MIN_BODY_BITS_AFTER_SIGNATURE = 104

# Максимальная длина BOC в base64 (256 КБ — с большим запасом).
MAX_BOC_BASE64_LENGTH = 350_000


class BocParseError(ValueError):
    """BOC не разобрался: не тот формат, обрезан, подозрительная структура."""


def _decode_boc(boc_base64: str) -> Cell:
    if not isinstance(boc_base64, str) or not boc_base64.strip():
        raise BocParseError("BOC пустой.")
    if len(boc_base64) > MAX_BOC_BASE64_LENGTH:
        raise BocParseError("BOC слишком большой.")
    try:
        raw = base64.b64decode(boc_base64, validate=True)
    except Exception as error:  # noqa: BLE001 — любой сбой декодирования
        raise BocParseError(f"BOC не декодируется из base64: {error}") from error
    try:
        return Cell.one_from_boc(raw)
    except Exception as error:  # noqa: BLE001
        raise BocParseError(f"BOC не является ячейкой TON: {error}") from error


def _split_signature(slice_: Any) -> tuple[bytes | None, Any]:
    """Отделить подпись от тела в разбираемой ячейке.

    Внешнее сообщение кошелька: signature:bits512body:... в ОДНОЙ ячейке.
    Если бит хватает на подпись + минимальное тело — считаем, что подпись есть.
    Возвращает (сигнатура | None, slice_ с оставшимся телом).
    """
    total_bits = slice_.remaining_bits
    if total_bits < SIGNATURE_BITS + MIN_BODY_BITS_AFTER_SIGNATURE:
        return None, slice_
    signature = slice_.load_bytes(SIGNATURE_BITS // 8)
    return signature, slice_


def _hash_of_body(slice_: Any) -> bytes:
    """Восстановить ячейку-тело (без подписи) и вернуть её хэш.

    Кошелёк подписывает именно хэш этой ячейки, поэтому «вырезать» сигнатуру
    мало — нужно пересобрать ячейку из оставшихся бит и refs побитово.
    """
    rebuilt = begin_cell()
    while slice_.remaining_bits >= 8:
        rebuilt = rebuilt.store_uint(slice_.load_uint(8), 8)
    if slice_.remaining_bits:  # остаток меньше байта
        rebuilt = rebuilt.store_uint(slice_.load_uint(slice_.remaining_bits),
                                     slice_.remaining_bits)
    while slice_.remaining_refs:
        rebuilt = rebuilt.store_ref(slice_.load_ref())
    return rebuilt.end_cell().hash


def verify_boc_signature(boc_base64: str, public_key: bytes) -> str:
    """Проверить, что BOC подписан ключом кошелька выплат.

    Адрес кошелька из подписи не выводится (ed25519 так не умеет), поэтому
    отправителя берём отдельно через extract_sender_address и сверяем с
    настройкой ton.payout_wallet.

    Поднимает BocParseError, если подписи нет или она не сходится.
    """
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != 32:
        raise BocParseError("Публичный ключ кошелька должен быть 32 байта.")

    cell = _decode_boc(boc_base64)
    slice_ = cell.begin_parse()
    signature, body_slice = _split_signature(slice_)
    if signature is None:
        raise BocParseError(
            "В BOC нет подписи: ожидалось внешнее сообщение кошелька."
        )

    body_hash = _hash_of_body(body_slice)
    try:
        VerifyKey(bytes(public_key)).verify(body_hash, signature)
    except BadSignatureError as error:
        raise BocParseError(
            "Подпись BOC не совпадает с ключом кошелька выплат."
        ) from error
    return "ok"


def parse_jetton_transfers(boc_base64: str) -> list[dict[str, Any]]:
    """Список jetton-переводов из подписанного BOC.

    Возвращает элементы:
      {queryId: str, amountNano: int, recipient: str (friendly), dest: str}

    Не-jetton сообщения игнорируются: в батче выплат их быть не должно, но
    кошелёк может добавить служебные — падать из-за них нельзя.
    """
    cell = _decode_boc(boc_base64)
    slice_ = cell.begin_parse()

    # Снимаем подпись, если она есть: дальше структура одинаковая.
    _, slice_ = _split_signature(slice_)

    try:
        wallet_id = slice_.load_uint(32)
        valid_until = slice_.load_uint(32)
        seqno = slice_.load_uint(32)
        op = slice_.load_uint(8)
    except Exception as error:  # noqa: BLE001 — структура не та
        raise BocParseError(
            f"BOC не похож на внешнее сообщение кошелька: {error}"
        ) from error

    logger.debug(
        "Parsing signed BOC: wallet_id=%s seqno=%s op=%s valid_until=%s",
        wallet_id,
        seqno,
        op,
        valid_until,
    )

    if op != WALLET_SEND_MESSAGES_OP:
        raise BocParseError(
            f"Неожидаемая операция кошелька: {op} (ожидалась "
            f"{WALLET_SEND_MESSAGES_OP} — отправка сообщений)."
        )

    transfers: list[dict[str, Any]] = []
    if slice_.remaining_refs == 0:
        raise BocParseError("В BOC нет ни одного сообщения.")

    current: Cell | None = slice_.load_ref()
    guard = 0
    while current is not None:
        guard += 1
        if guard > MAX_MESSAGES_PER_BOC:
            raise BocParseError(
                f"Слишком много сообщений в BOC (> {MAX_MESSAGES_PER_BOC})."
            )

        item = current.begin_parse()
        try:
            item.load_uint(8)  # send_mode — для сверки не нужен
            message_cell = item.load_ref()
            next_cell = item.load_ref() if item.remaining_refs else None
        except Exception as error:  # noqa: BLE001
            raise BocParseError(
                f"Элемент списка сообщений не разобрался: {error}"
            ) from error

        try:
            message = MessageAny.deserialize(message_cell.begin_parse())
        except Exception:  # noqa: BLE001 — не наше сообщение, пропускаем
            current = next_cell
            continue

        body = message.body.begin_parse()
        if body.remaining_bits < 32:
            current = next_cell
            continue
        if body.load_uint(32) != JETTON_TRANSFER_OP:
            current = next_cell
            continue
        if body.remaining_bits < 64:
            raise BocParseError("Тело jetton-перевода обрезано: нет query_id.")

        query_id = body.load_uint(64)
        try:
            amount_nano = body.load_coins()
            recipient = body.load_address()
        except Exception as error:  # noqa: BLE001
            raise BocParseError(
                f"Тело jetton-перевода повреждено: {error}"
            ) from error
        if recipient is None:
            raise BocParseError("В jetton-переводе нет адреса получателя.")

        transfers.append(
            {
                "queryId": str(query_id),
                "amountNano": amount_nano,
                "recipient": recipient.to_str(is_user_friendly=True),
                "dest": message.info.dest.to_str(is_user_friendly=True),
            }
        )
        current = next_cell

    if not transfers:
        raise BocParseError(
            "В BOC нет ни одного jetton-перевода ROOT."
        )
    return transfers


def extract_sender_address(boc_base64: str) -> str:
    """Адрес кошелька-отправителя из BOC (src первого внутреннего сообщения).

    Нужен, чтобы сверить с ton.payout_wallet: платить должен только он.
    """
    cell = _decode_boc(boc_base64)
    slice_ = cell.begin_parse()
    try:
        _, slice_ = _split_signature(slice_)
        for _ in range(3):
            slice_.load_uint(32)
        slice_.load_uint(8)
        if slice_.remaining_refs == 0:
            raise BocParseError("В BOC нет сообщений.")
        current = slice_.load_ref()
        item = current.begin_parse()
        item.load_uint(8)
        message = MessageAny.deserialize(item.load_ref().begin_parse())
        src = message.info.src
        if src is None:
            raise BocParseError("У сообщения нет отправителя.")
        return src.to_str(is_user_friendly=True)
    except BocParseError:
        raise
    except Exception as error:  # noqa: BLE001
        raise BocParseError(
            f"Не удалось получить отправителя из BOC: {error}"
        ) from error


def same_address(left: str, right: str) -> bool:
    """Сравнение TON-адресов по raw-форме (wc + хеш).

    Устойчиво к bounceable/non-bounceable и разным регистрам base64url:
    один и тот же кошелёк может быть представлен как kQ… и EQ…
    """
    try:
        return Address(left).to_str(is_user_friendly=False) == Address(
            right
        ).to_str(is_user_friendly=False)
    except Exception:  # noqa: BLE001
        return False
