"""Реальный BOC от Tonkeeper — эталон для регресс-тестов.

Файл `data/tonkeeper_boc.b64` содержит настоящее подписанное сообщение,
которое Tonkeeper вернул на проде (тестнет, батч batch-07fdd0d5…, 155 ROOT).
Ключей внутри нет: это публичное подписанное сообщение.

Оно ценно тем, что ломало три версии парсера подряд. Собранные вручную
обёртки этого не выявляли: тесты и парсер строили ячейку одним кодом, и
ошибка взаимно компенсировалась. Реальное сообщение показало правду:

  корень : 919 бит, 1 ref (40 бит) — это ext_in_msg_info
  тело   : 642 бит, 1 ref, op = 0x7369676e
  подпись: последние 512 бит тела, signed part = 130 бит
"""

# Настоящее сообщение из прода. Не менять: это эталон разбора.
TONKEEPER_BOC_B64 = (
    "te6cckEBBAEA6wAB5YgAVB0osDGkltcAVSwUFupslei4BOpaYr6OYJXV+F3Jo54Dm0s7c////+tYLeVw"
    "AAAAPMKmEnp5xgIcvKL1F69AsFqqsj0hZfI+lvrsvQ0AGIEjV4g16vfNnveCZYa0aSMa2aqMoqDLbnGN"
    "9lF47DL7oAsBAgoOw8htAwIDAAAAz2IAYdN5X2FHKbNSbGn2sIsajSluhXgcjPKGHztgffOTxAugF9eE"
    "AAAAAAAAAAAAAAAAAAAPin6lAnmLQXl7ulRQOb3zsAgBh03lfYUcps1JsafawixqNKW6FeByM8oYfO2B"
    "985PEC4BGXqUVg=="
)

# Публичный ключ кошелька выплат (testnet), он же в CMS на проде.
TONKEEPER_PUBLIC_KEY_HEX = (
    "cc7ac02e489e62939685aa3f151459a15dd4286f0eb6da2d7f3f3b386771f3af"
)

# Ожидаемые значения из этого сообщения.
TONKEEPER_WALLET_ID = 2147483645
TONKEEPER_VALID_UNTIL = 1795538094
TONKEEPER_SEQNO = 7
TONKEEPER_QUERY_ID = "178326773585132116"
TONKEEPER_AMOUNT_NANO = 155 * 10**8
