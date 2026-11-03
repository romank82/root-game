import type { EngineMission } from '../api/engineApi'
import { ErrorWithCode } from './ErrorWithCode'

interface MissionModalProps {
  mission: EngineMission
  onClose: () => void
  onAccept: () => void
  isAccepting: boolean
  // Текст ошибки взятия миссии (GPS/сервер). Показывается над кнопками.
  error?: string | null
}

/**
 * Модальное окно «Просмотр» карточки миссии: полное описание, цена входа,
 * требуемые ключи, награды и кнопка «Взять миссию».
 *
 * Оверлей — position: fixed поверх экрана (паттерн админских модалок,
 * см. PlayersSection). Клик по фону закрывает окно, пока идёт accept.
 */
export function MissionModal({
  mission,
  onClose,
  onAccept,
  isAccepting,
  error,
}: MissionModalProps) {
  const hasEntryPrice =
    typeof mission.entryRoot === 'number' && mission.entryRoot > 0

  const requiredItems = mission.requiredItems ?? []

  const rewardLabels = (mission.rewards ?? [])
    .map((reward) => {
      if (reward.type === 'currency' && typeof reward.amount === 'number') {
        return `До ${reward.amount} ROOT`
      }
      if (reward.type === 'item' && reward.itemId) {
        return `Предмет: ${reward.itemCode ?? reward.itemId}`
      }
      if (reward.type === 'story_node' && reward.storyNodeId) {
        return `Сюжетный узел: ${reward.storyNodeId}`
      }
      return null
    })
    .filter((label): label is string => label !== null)

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 110,
        background: 'rgba(2, 8, 6, 0.66)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        overflowY: 'auto',
        padding: '40px 16px',
      }}
      onClick={() => {
        if (!isAccepting) onClose()
      }}
    >
      <div
        style={{
          background: '#0d1c18',
          border: '1px solid rgba(190, 255, 226, 0.24)',
          borderRadius: 12,
          padding: 20,
          width: 'min(560px, 100%)',
          boxShadow: '0 12px 40px rgba(0, 0, 0, 0.5)',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <p
          style={{
            margin: '0 0 18px',
            color: '#65e9ae',
            fontSize: 10,
            letterSpacing: '0.12em',
          }}
        >
          МИССИЯ
        </p>

        <h3
          style={{
            margin: '0 0 12px',
            color: '#effff6',
            fontSize: 21,
            letterSpacing: '-0.025em',
          }}
        >
          {mission.title}
        </h3>

        {mission.description && (
          <p
            style={{
              margin: '0 0 16px',
              color: '#d2e6dc',
              fontSize: 15,
              lineHeight: 1.7,
              whiteSpace: 'pre-wrap',
            }}
          >
            {mission.description}
          </p>
        )}

        {hasEntryPrice && (
          <p style={{ margin: '0 0 8px', color: '#b7ffdb' }}>
            Вход: {mission.entryRoot} ROOT
          </p>
        )}

        {requiredItems.length > 0 && (
          <p style={{ margin: '0 0 8px', color: '#b7ffdb' }}>
            Требуемые ключи:{' '}
            {requiredItems
              .map(
                (requirement) =>
                  `${requirement.itemCode ?? requirement.itemId} (${requirement.quantity})`,
              )
              .join(', ')}
          </p>
        )}

        {rewardLabels.length > 0 && (
          <p style={{ margin: '0 0 16px', color: '#b7ffdb' }}>
            Возможные награды: {rewardLabels.join(', ')}
          </p>
        )}

        {error && (
          <ErrorWithCode
            message={error}
            style={{
              margin: '0 0 12px',
              color: '#ffd0d0',
              fontSize: 13,
            }}
          />
        )}

        <div
          style={{
            display: 'flex',
            gap: 10,
            flexWrap: 'wrap',
            marginTop: 20,
          }}
        >
          <button
            onClick={onAccept}
            disabled={isAccepting}
            style={{
              background: '#00ff88',
              color: '#000',
              border: 'none',
              padding: '10px 18px',
              borderRadius: 6,
              fontWeight: 'bold',
              fontSize: 13,
              cursor: isAccepting ? 'wait' : 'pointer',
            }}
          >
            {isAccepting
              ? 'ПОЛУЧЕНИЕ GPS…'
              : 'ВЗЯТЬ МИССИЮ'}
          </button>

          <button
            onClick={onClose}
            disabled={isAccepting}
            style={{
              background: 'transparent',
              color: '#b7ffdb',
              border: '1px solid rgba(174, 255, 219, 0.35)',
              padding: '10px 18px',
              borderRadius: 6,
              fontSize: 13,
              cursor: isAccepting ? 'wait' : 'pointer',
            }}
          >
            ОТМЕНА
          </button>
        </div>
      </div>
    </div>
  )
}
