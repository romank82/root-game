import { Address, beginCell } from '@ton/core'

// TEP-74 transfer, OP 0xf8a7ea5. Тот же код на бэкенде
// (ton_connect_parser.JETTON_TRANSFER_OP) — менять только парой.
export const JETTON_TRANSFER_OP = 0xf8a7ea5

/**
 * Тело TEP-74 transfer в base64 BOC.
 *
 * Порядок полей фиксирован стандартом:
 *   op:uint32 = 0xf8a7ea5
 *   query_id:uint64         <- ключ сверки с заявкой на бэкенде
 *   amount:coins            <- сумма ROOT в nano
 *   destination:MsgAddress  <- адрес ВЛАДЕЛЬЦА (игрока), НЕ его jetton-wallet
 *   response_destination:MsgAddress (none)
 *   custom_payload:(Maybe ^Cell) = 0
 *   forward_ton_amount:coins = 0
 *   forward_payload:(Either Cell ^Cell) = 0
 *
 * destination — это адрес нового ВЛАДЕЛЬЦА токенов (спецификация TEP-74,
 * «address of the new owner of the jettons»), то есть обычный TON-адрес
 * игрока. Если подставить сюда jetton-кошелёк игрока, минтер создаст
 * jetton-кошелёк ДЛЯ jetton-кошелька: токены уйдут на адрес, к которому у
 * игрока нет доступа. Проверено на реальной выплате — 155 ROOT так и
 * застряли.
 *
 * query_id пишется числом: сервер читает его как uint64 и сверяет со
 * значением из PayoutAttempt.query_id. Если он не совпадёт, подтверждение
 * отклонится — это защита от подмены, не баг.
 */
export function buildTransferPayload(
  amountNano: number,
  ownerAddress: string,
  queryId: string,
): string {
  const cell = beginCell()
    .storeUint(JETTON_TRANSFER_OP, 32)
    .storeUint(BigInt(queryId), 64)
    .storeCoins(amountNano)
    .storeAddress(Address.parse(ownerAddress))
    .storeAddress(null) // response_destination
    .storeMaybeRef(null) // custom_payload
    .storeCoins(0) // forward_ton_amount
    .storeMaybeRef(null) // forward_payload
    .endCell()

  return cell.toBoc().toString('base64')
}
