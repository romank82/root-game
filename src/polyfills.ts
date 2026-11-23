/**
 * Полифиллы Node-глобалов для браузера.
 *
 * Зачем: `@ton/core` и `@ton/crypto` (тянутся через `@tonconnect/ui-react` для
 * оплаты батчей) используют `Buffer` — глобал Node, которого в браузере нет.
 * Без полифилла падает ВЕСЬ бандл: `Uncaught ReferenceError: Buffer is not
 * defined`, `#root` остаётся пустым, и админка с игрой не открываются.
 *
 * Импортировать этот файл нужно ПЕРВЫМ в `main.tsx`: ES-модули выполняются в
 * порядке объявления импортов, поэтому полифилл успевает встать до того, как
 * `@ton/core` начнёт обращаться к `Buffer` при инициализации.
 */
import { Buffer } from 'buffer'

const globalScope = globalThis as typeof globalThis & {
  Buffer?: typeof Buffer
}

if (typeof globalScope.Buffer === 'undefined') {
  globalScope.Buffer = Buffer
}

export {}
