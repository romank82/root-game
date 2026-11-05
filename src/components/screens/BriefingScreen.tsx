import type { AuthStatus } from '../../types/game'
import { useTranslation } from 'react-i18next'

interface BriefingScreenProps {
  authStatus: AuthStatus
  authError: string
  accepted: boolean
  setAccepted: (accepted: boolean) => void
  onActivate: () => void
}

export function BriefingScreen({
  authStatus,
  authError,
  accepted,
  setAccepted,
  onActivate,
}: BriefingScreenProps) {
  const { t } = useTranslation(['briefing', 'common'])
  if (authStatus !== 'authenticated') {
    return (
      <section className="briefing">
        <div className="packet-icon">◈</div>
        <p className="eyebrow">CHIMERA PROTOCOL / ACCESS GATE</p>
        <h1>
          {authStatus === 'checking'
            ? t('briefing:loading.checkingSession')
            : t('briefing:loading.requiresTelegram')}
        </h1>
        <p className="intro">
          {authStatus === 'checking'
            ? t('briefing:loading.checkingConfirmed')
            : authError}
        </p>
        {authStatus !== 'checking' && (
          <p className="safe-note">
            {t('briefing:loading.openInBot')}
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="briefing">
      <div className="packet-icon">▣</div>
      <p className="eyebrow">{t('briefing:packet.incoming')}</p>
      <h1>
        {t('briefing:packet.packet')}
        <br />
        {t('briefing:packet.noSender')}
      </h1>

      <div className="packet-data">
        <div>
          <span>{t('briefing:packet.sender')}</span>
          <b>{t('briefing:packet.notDefined')}</b>
        </div>
        <div>
          <span>{t('briefing:packet.integrity')}</span>
          <b className="warning">61%</b>
        </div>
        <div>
          <span>{t('briefing:packet.status')}</span>
          <b>{t('briefing:packet.waitingObserver')}</b>
        </div>
      </div>

      <p className="intro">
        {t('briefing:disclaimer.title')}
      </p>

      <label className="consent">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(event) => setAccepted(event.target.checked)}
        />
        <span>
          {t('briefing:disclaimer.consent')}
        </span>
      </label>

      <button
        className="primary-button"
        disabled={!accepted}
        onClick={onActivate}
      >
        {t('briefing:buttons.activate')} <span>→</span>
      </button>

      <p className="safe-note">
        {t('briefing:buttons.note')}
      </p>
    </section>
  )
}
