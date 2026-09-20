import type { AuthStatus } from '../../types/game'

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
  if (authStatus !== 'authenticated') {
    return (
      <section className="briefing">
        <div className="packet-icon">◈</div>
        <p className="eyebrow">CHIMERA PROTOCOL / ACCESS GATE</p>
        <h1>
          {authStatus === 'checking'
            ? 'Проверяем\nсессию'
            : 'Требуется\nTelegram'}
        </h1>
        <p className="intro">
          {authStatus === 'checking'
            ? 'Проверяем подтверждённую игровую сессию…'
            : authError}
        </p>
        {authStatus !== 'checking' && (
          <p className="safe-note">
            ОТКРОЙТЕ ИГРУ КНОПКОЙ В ЧАТЕ С @HIMERAPROTOCOLBOT
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="briefing">
      <div className="packet-icon">▣</div>
      <p className="eyebrow">ВХОДЯЩИЙ АРХИВНЫЙ ПАКЕТ</p>
      <h1>
        Пакет
        <br />
        без отправителя
      </h1>

      <div className="packet-data">
        <div>
          <span>ОТПРАВИТЕЛЬ</span>
          <b>НЕ ОПРЕДЕЛЁН</b>
        </div>
        <div>
          <span>ЦЕЛОСТНОСТЬ</span>
          <b className="warning">61%</b>
        </div>
        <div>
          <span>СТАТУС</span>
          <b>ОЖИДАНИЕ НАБЛЮДАТЕЛЯ</b>
        </div>
      </div>

      <p className="intro">
        «Протокол Химера» — интерактивная художественная игра. Она не
        получает доступ к вашим файлам, настройкам или устройству. Вы
        можете остановить участие в любой момент.
      </p>

      <label className="consent">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(event) => setAccepted(event.target.checked)}
        />
        <span>
          Я понимаю, что это игровая симуляция, и хочу продолжить.
        </span>
      </label>

      <button
        className="primary-button"
        disabled={!accepted}
        onClick={onActivate}
      >
        АКТИВИРОВАТЬ ПРОТОКОЛ <span>→</span>
      </button>

      <p className="safe-note">
        ДОСТУП МОЖНО ОТКЛЮЧИТЬ В ЛЮБОЙ МОМЕНТ
      </p>
    </section>
  )
}
