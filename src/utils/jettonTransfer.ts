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
 *   destination:MsgAddress  <- jetton-wallet получателя
 *   response_destination:MsgAddress (none)
 *   custom_payload:(Maybe ^Cell) = 0
 *   forward_ton_amount:coins = 0
 *   forward_payload:(Either Cell ^Cell) = 0
 *
 * query_id пишется числом: сервер читает его как uint64 и сверяет со
 * значением из PayoutAttempt.query_id. Если он не совпадёт, подтверждение
 * отклонится — это защита от подмены, не баг.
 */
export function buildTransferPayload(
  amountNano: number,
  jettonWalletAddress: string,
  queryId: string,
): string {
  const cell = beginCell()
    .storeUint(JETTON_TRANSFER_OP, 32)
    .storeUint(BigInt(queryId), 64)
    .storeCoins(amountNano)
    .storeAddress(Address.parse(jettonWalletAddress))
    .storeAddress(null) // response_destination
    .storeMaybeRef(null) // custom_payload
    .storeCoins(0) // forward_ton_amount
    .storeMaybeRef(null) // forward_payload
    .endCell()

  return cell.toBoc().toString('base64')
}
