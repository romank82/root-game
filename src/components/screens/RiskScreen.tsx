import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Screen } from '../../types/game'
import {
  getRiskState,
  unlockRiskSection,
  type EngineRiskAccess,
} from '../../api/engineApi'
import { ErrorWithCode } from '../ErrorWithCode'

// Раздел «Риск» (docs/risk-section-contract.md).
// Это ТОЛЬКО контейнер: состояние доступа, разовая оплата газом и заглушка
// на месте будущих мини-игр. Игры сюда не подключены.
//
// Три состояния приходят с сервера:
//   hidden   — раздел скрыт админом, экран не рендерится вообще;
//   locked   — видим, но требует разовой оплаты газом;
//   unlocked — доступен (грант выдан или админ открыл раздел всем).

type RiskScreenProps = {
  onScreenChange: (screen: Screen) => void
}

// Газ — Numeric(18,4) на сервере: приходит строкой. Показываем без хвостовых
// нулей, но не теряя дробную часть (например 100.5 газа).
function formatGas(value: string): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return value
  return Number.isInteger(parsed) ? String(parsed) : String(parsed).replace(/\.?0+$/, '')
}

export function RiskScreen({ onScreenChange }: RiskScreenProps) {
  const { t } = useTranslation(['risk', 'common'])
  const [access, setAccess] = useState<EngineRiskAccess | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [paying, setPaying] = useState(false)
  const [confirming, setConfirming] = useState(false)

  // Функция загрузки состояния. Не вызывает setState синхронно в теле
  // рендера — только из обработчиков и эффекта.
  const loadState = useCallback(() => {
    getRiskState()
      .then((data) => setAccess(data))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    getRiskState()
      .then((data) => {
        if (!cancelled) setAccess(data)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // hidden: раздел не показываем вообще — уводим обратно в «Ещё»/контур.
  useEffect(() => {
    if (access?.state === 'hidden') {
      onScreenChange('terminal')
    }
  }, [access, onScreenChange])

  const handlePay = () => {
    if (!access || paying) return
    setPaying(true)
    setError(null)
    unlockRiskSection()
      .then((data) => {
        setAccess(data)
        setConfirming(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        // Состояние могло измениться (например, админ открыл раздел) —
        // перечитываем, но показываем и саму ошибку.
        loadState()
      })
      .finally(() => setPaying(false))
  }

  if (loading) {
    return (
      <section className="risk">
        <p className="eyebrow">{t('risk:header.eyebrow')}</p>
        <h2>{t('risk:header.title')}</h2>
        <p>{t('common:loading')}</p>
      </section>
    )
  }

  if (!access) {
    return (
      <section className="risk">
        <p className="eyebrow">{t('risk:header.eyebrow')}</p>
        <h2>{t('risk:header.title')}</h2>
        <ErrorWithCode message={error} className="admin-alert admin-error" />
      </section>
    )
  }

  if (access.state === 'hidden') {
    return null
  }

  const gasCost = formatGas(access.gasCost)
  const gasBalance = formatGas(access.gasBalance)
  const enoughGas = Number(access.gasBalance) >= Number(access.gasCost)

  if (access.state === 'unlocked') {
    return (
      <section className="risk">
        <p className="eyebrow">{t('risk:header.eyebrow')}</p>
        <h2>{t('risk:header.title')}</h2>
        <article className="message-card">
          <p>{t('risk:unlocked.placeholder')}</p>
        </article>
      </section>
    )
  }

  // state === 'locked'
  return (
    <section className="risk">
      <p className="eyebrow">{t('risk:header.eyebrow')}</p>
      <h2>{t('risk:header.title')}</h2>

      <ErrorWithCode message={error} className="admin-alert admin-error" />

      <article className="message-card">
        <p>{t('risk:locked.message', { cost: gasCost })}</p>
        <p className="risk-balance">
          {t('risk:locked.balance', { balance: gasBalance })}
        </p>

        {!confirming && (
          <>
            <p className="risk-notice">{t('risk:locked.notice')}</p>
            <div className="risk-actions">
              <button
                type="button"
                className="btn-primary"
                disabled={!enoughGas}
                onClick={() => setConfirming(true)}
              >
                {t('risk:locked.payButton')}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => onScreenChange('terminal')}
              >
                {t('risk:locked.declineButton')}
              </button>
            </div>
            {!enoughGas && (
              <p className="risk-warning">{t('risk:locked.notEnoughGas')}</p>
            )}
          </>
        )}

        {confirming && (
          <>
            <p className="risk-warning">
              {t('risk:confirm.message', {
                cost: gasCost,
                remaining: formatGas(
                  String(Number(access.gasBalance) - Number(access.gasCost)),
                ),
              })}
            </p>
            <div className="risk-actions">
              <button
                type="button"
                className="btn-primary"
                disabled={paying}
                onClick={handlePay}
              >
                {paying
                  ? t('risk:confirm.paying')
                  : t('risk:confirm.confirmButton')}
              </button>
              <button
                type="button"
                className="btn-ghost"
                disabled={paying}
                onClick={() => setConfirming(false)}
              >
                {t('risk:confirm.cancelButton')}
              </button>
            </div>
          </>
        )}
      </article>
    </section>
  )
}