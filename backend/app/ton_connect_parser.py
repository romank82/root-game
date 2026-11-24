"""Разбор подписанного TON Connect BOC и проверка подписи кошелька.

TON Connect возвращает base64 BOC — внешнее сообщение кошелька с подписью.
Формат зависит от ВЕРСИИ кошелька, и они несовместимы:

  V4 (WalletV4R2):
    [signature:512][wallet_id:32][valid_until:32][seqno:32][op:8=1]
    + ref -> список WalletMessage(send_mode:8 + ref MessageAny)
    Подпись — в НАЧАЛЕ; сообщения — цепочкой ref'ов.

  V5R1 (текущий Tonkeeper):
    [op:32=0x7369676e "sign"][wallet_id:32][valid_until:32][seqno:32]
    + флаги и ref actions, а [signature:512] — в КОНЦЕ бит.
    actions — дерево: узел = ref пред. узла + ref action
    (action: 0x0ec3c86d:32 + send_mode:8 + ref MessageAny)

Перепутать форматы нельзя: парсер V4 прочитает op-код V5 как wallet_id и
выдаст бессмысленные значения, а подпись станет искать не там. Версия
определяется по первым 32 битам: 0x7369676e — ASCII "sign", однозначный
признак V5.

Задачи модуля:
  1. parse_jetton_transfers — вытащить переводы из любого формата.
  2. verify_boc_signature — убедиться, что BOC подписан нужным ключом.

Ограничение pytoniq 0.1.43: WalletMessage.deserialize — заглушка (`pass`),
поэтому send_mode и ref сообщения читаются вручную.
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

# Wallet V4: op=1 означает «отправить список сообщений».
WALLET_SEND_MESSAGES_OP = 1

# Wallet V5R1: op-код подписанного внешнего сообщения (ASCII "sign").
WALLET_V5_SIGNED_OP = 0x7369676E

# OP-код одной action внутри V5 (SendMsg).
ACTION_SEND_MSG_OP = 0x0EC3C86D

# Максимум переводов в одном BOC: защита от гигантских payload'ов.
MAX_MESSAGES_PER_BOC = 255

# Максимальная длина BOC в base64 (256 КБ — с большим запасом).
MAX_BOC_BASE64_LENGTH = 350_000

# Длина подписи ed25519 в битах.
SIGNATURE_BITS = 512

# Минимум бит после подписи V4: wallet_id(32)+valid_until(32)+seqno(32)+op(8).
MIN_BODY_BITS_AFTER_SIGNATURE = 104

# V5: поля после op-кода — wallet_id(32)+valid_until(32)+seqno(32) = 96 бит.
MIN_BITS_AFTER_V5_OP = 96


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


def _unwrap_external_envelope(cell: Cell) -> Cell:
    """Снять обёртку внешнего сообщения, если она есть.

    TON Connect возвращает не «голое» тело кошелька, а внешнее сообщение:
      ext_in_msg_info$10 src:MsgAddress import_fee:Grams body:^Cell
    Первые биты там — служебные (magic 0b10 + адрес), а не op-код кошелька.
    Если разбирать такую ячейку как тело, всё съезжает: детектор версии видит
    не 0x7369676e, решает «V4», берёт мусор как подпись и выдаёт
    «подпись не совпадает» — хотя подпись верна.

    Распознаём по первым двум битам: 0b10 = ext_in_msg_info.
    Тело лежит в ref; биты самой обёртки — только служебные поля.
    """
    total = cell.bits.__len__()
    if total < 2 or not cell.refs:
        return cell

    peek = cell.begin_parse()
    if peek.load_uint(2) != 0b10:
        return cell

    # Точный признак: в ref лежит подписанное V5-тело, то есть первые 32 бита
    # этого ref — op-код 0x7369676e. Проверка по битам самой ячейки ненадёжна:
    # у ext_in с реальным адресом отправителя бит много (адрес = 267 бит), и
    # порог «мало бит» не срабатывал — обёртка оставалась неснятой.
    body_candidate = cell.refs[0]
    if body_candidate.bits.__len__() < 32:
        return cell
    body_peek = body_candidate.begin_parse()
    if body_peek.load_uint(32) != WALLET_V5_SIGNED_OP:
        return cell

    return body_candidate


def _detect_wallet_version(slice_: Any) -> str:
    """Версия кошелька по первым 32 битам: "v5" или "v4".

    V5 всегда начинается с op-кода 0x7369676e. У V4 первыми идут биты
    подписи, и совпасть со "sign" они могут с вероятностью 2^-32.

    Slice не потребляется — вызывающий разбирает заново.
    """
    if slice_.remaining_bits < 32:
        raise BocParseError("BOC слишком короткий, чтобы определить кошелёк.")
    peek = slice_.copy()
    return "v5" if peek.load_uint(32) == WALLET_V5_SIGNED_OP else "v4"


def _split_signature_v4(slice_: Any) -> tuple[bytes | None, Any]:
    """Отделить подпись V4 (в НАЧАЛЕ ячейки) от тела.

    Если бит хватает на подпись + минимальное тело — подпись есть.
    """
    if slice_.remaining_bits < SIGNATURE_BITS + MIN_BODY_BITS_AFTER_SIGNATURE:
        return None, slice_
    return slice_.load_bytes(SIGNATURE_BITS // 8), slice_


def _split_signature_v5(cell: Cell) -> tuple[bytes, Cell]:
    """Разделить V5-сообщение: подпись — последние 512 бит той же ячейки.

    V5 собирается как «тело + подпись», поэтому сигнатура лежит в конце.
    Возвращает (подпись, ячейка тела).
    """
    total_bits = cell.bits.__len__()
    if total_bits < SIGNATURE_BITS + MIN_BITS_AFTER_V5_OP:
        raise BocParseError(
            "V5-сообщение слишком короткое: нет места под подпись."
        )

    body_bits = total_bits - SIGNATURE_BITS
    parser = cell.begin_parse()
    rebuilt = begin_cell()
    remaining = body_bits
    while remaining >= 8:
        rebuilt = rebuilt.store_uint(parser.load_uint(8), 8)
        remaining -= 8
    if remaining > 0:
        rebuilt = rebuilt.store_uint(parser.load_uint(remaining), remaining)
    while parser.remaining_refs:
        rebuilt = rebuilt.store_ref(parser.load_ref())
    body_cell = rebuilt.end_cell()

    sig_parser = cell.begin_parse()
    if body_bits > 0:
        sig_parser.load_bits(body_bits)
    signature = sig_parser.load_bytes(SIGNATURE_BITS // 8)
    return signature, body_cell


def _hash_of_body(slice_: Any) -> bytes:
    """Восстановить ячейку-тело (V4, без префикса подписи) и вернуть хэш.

    Кошелёк подписывает хэш ячейки-тела, поэтому «вырезать» сигнатуру мало —
    нужно пересобрать ячейку из оставшихся бит и refs побитово.
    """
    rebuilt = begin_cell()
    while slice_.remaining_bits >= 8:
        rebuilt = rebuilt.store_uint(slice_.load_uint(8), 8)
    remainder = slice_.remaining_bits
    if remainder > 0:
        rebuilt = rebuilt.store_uint(slice_.load_uint(remainder), remainder)
    while slice_.remaining_refs:
        rebuilt = rebuilt.store_ref(slice_.load_ref())
    return rebuilt.end_cell().hash


def verify_boc_signature(boc_base64: str, public_key: bytes) -> str:
    """Проверить, что BOC подписан ключом кошелька выплат.

    Поддерживает V4 (подпись в начале) и V5R1 (подпись в конце).

    Адрес кошелька из подписи не выводится (ed25519 так не умеет), поэтому
    отправителя берём отдельно через extract_sender_address и сверяем с
    настройкой ton.payout_wallet.

    Поднимает BocParseError, если подписи нет или она не сходится.
    """
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != 32:
        raise BocParseError("Публичный ключ кошелька должен быть 32 байта.")

    cell = _unwrap_external_envelope(_decode_boc(boc_base64))
    version = _detect_wallet_version(cell.begin_parse())

    if version == "v5":
        signature, body_cell = _split_signature_v5(cell)
        body_hash = body_cell.hash
    else:
        slice_ = cell.begin_parse()
        signature, body_slice = _split_signature_v4(slice_)
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


def _iter_v4_message_cells(slice_: Any) -> list[Cell]:
    """Ячейки MessageAny из V4: цепочка ref'ов, по сообщению на элемент."""
    message_cells: list[Cell] = []
    if slice_.remaining_refs == 0:
        return message_cells

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
        message_cells.append(message_cell)
        current = next_cell
    return message_cells


def _v5_actions_from_packed(packed_cell: Cell) -> Cell:
    """Достать дерево actions из обёртки packed.

    V5 кладёт действия в обёртку:
      packed = [signed:1][ref actions][ref external:1]
    Поэтому первый ref — это уже дерево действий, а не сами действия.
    Если refs нет — структура не та, сообщаем понятно.
    """
    if not packed_cell.refs:
        raise BocParseError(
            "В V5-сообщении нет ссылки на список действий."
        )
    return packed_cell.refs[0]


def _collect_v5_message_cells(actions_cell: Cell) -> list[Cell]:
    """Ячейки MessageAny из V5-дерева actions.

    Каждый узел: ref на предыдущий узел + ref на action. Обход идёт от
    последнего к первому, поэтому результат переворачиваем — нужен исходный
    порядок переводов.
    """
    message_cells: list[Cell] = []
    node: Cell | None = actions_cell
    guard = 0
    while node is not None and len(node.refs) >= 2:
        guard += 1
        if guard > MAX_MESSAGES_PER_BOC:
            raise BocParseError(
                f"Слишком много действий в BOC (> {MAX_MESSAGES_PER_BOC})."
            )
        prev_node = node.refs[0]
        action = node.refs[1]

        parser = action.begin_parse()
        try:
            op = parser.load_uint(32)
            parser.load_uint(8)  # send_mode
            if op == ACTION_SEND_MSG_OP and parser.remaining_refs:
                message_cells.append(parser.load_ref())
        except Exception as error:  # noqa: BLE001
            raise BocParseError(f"Действие V5 не разобралось: {error}") from error

        node = prev_node

    message_cells.reverse()
    return message_cells


def _transfers_from_message_cells(
    message_cells: list[Cell],
) -> list[dict[str, Any]]:
    """Разобрать ячейки MessageAny в переводы TEP-74.

    Не-jetton сообщения (служебные от кошелька) пропускаются.
    """
    transfers: list[dict[str, Any]] = []
    for message_cell in message_cells:
        try:
            message = MessageAny.deserialize(message_cell.begin_parse())
        except Exception:  # noqa: BLE001 — не наше сообщение
            continue

        body = message.body.begin_parse()
        if body.remaining_bits < 32:
            continue
        if body.load_uint(32) != JETTON_TRANSFER_OP:
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
    return transfers


def parse_jetton_transfers(boc_base64: str) -> list[dict[str, Any]]:
    """Список jetton-переводов из подписанного BOC (V4 и V5R1).

    Возвращает элементы:
      {queryId: str, amountNano: int, recipient: str, dest: str}

    Порядок переводов сохраняется тем же, что в BOC.
    """
    cell = _unwrap_external_envelope(_decode_boc(boc_base64))
    version = _detect_wallet_version(cell.begin_parse())

    if version == "v5":
        _signature, body_cell = _split_signature_v5(cell)
        body = body_cell.begin_parse()
        try:
            op = body.load_uint(32)
            body.load_uint(32)  # wallet_id
            body.load_uint(32)  # valid_until
            body.load_uint(32)  # seqno
        except Exception as error:  # noqa: BLE001
            raise BocParseError(
                f"V5-сообщение не разобралось: {error}"
            ) from error
        if op != WALLET_V5_SIGNED_OP:
            raise BocParseError(f"Неожидаемая операция V5-кошелька: 0x{op:x}.")
        if body.remaining_refs == 0:
            raise BocParseError("В V5-сообщении нет действий.")
        message_cells = _collect_v5_message_cells(
            _v5_actions_from_packed(body.load_ref())
        )
    else:
        slice_ = cell.begin_parse()
        signature, slice_ = _split_signature_v4(slice_)
        try:
            slice_.load_uint(32)  # wallet_id
            slice_.load_uint(32)  # valid_until
            slice_.load_uint(32)  # seqno
            op = slice_.load_uint(8)
        except Exception as error:  # noqa: BLE001 — структура не та
            raise BocParseError(
                f"BOC не похож на внешнее сообщение кошелька: {error}"
            ) from error
        logger.debug(
            "Parsing V4 BOC: signature=%s",
            "present" if signature else "absent",
        )
        if op != WALLET_SEND_MESSAGES_OP:
            raise BocParseError(
                f"Неожидаемая операция кошелька: {op} (ожидалась "
                f"{WALLET_SEND_MESSAGES_OP} — отправка сообщений)."
            )
        message_cells = _iter_v4_message_cells(slice_)

    if not message_cells:
        raise BocParseError("В BOC нет ни одного сообщения.")

    transfers = _transfers_from_message_cells(message_cells)
    if not transfers:
        raise BocParseError("В BOC нет ни одного jetton-перевода ROOT.")
    return transfers


def extract_sender_address(boc_base64: str) -> str:
    """Адрес кошелька-отправителя из BOC (src первого внутреннего сообщения).

    Нужен, чтобы сверить с ton.payout_wallet: платить должен только он.
    Работает для V4 и V5R1.
    """
    cell = _unwrap_external_envelope(_decode_boc(boc_base64))
    version = _detect_wallet_version(cell.begin_parse())

    try:
        if version == "v5":
            _signature, body_cell = _split_signature_v5(cell)
            body = body_cell.begin_parse()
            for _ in range(4):  # op, wallet_id, valid_until, seqno
                body.load_uint(32)
            message_cells = _collect_v5_message_cells(
            _v5_actions_from_packed(body.load_ref())
        )
        else:
            slice_ = cell.begin_parse()
            _signature, slice_ = _split_signature_v4(slice_)
            for _ in range(3):  # wallet_id, valid_until, seqno
                slice_.load_uint(32)
            slice_.load_uint(8)  # op
            message_cells = _iter_v4_message_cells(slice_)

        if not message_cells:
            raise BocParseError("В BOC нет сообщений.")
        message = MessageAny.deserialize(message_cells[0].begin_parse())
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
