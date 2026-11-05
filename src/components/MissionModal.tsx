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
      className="mission-modal-overlay"
      onClick={() => {
        if (!isAccepting) onClose()
      }}
    >
      <div
        className="mission-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <p className="mission-modal-eyebrow">МИССИЯ</p>

        <h3 className="mission-modal-title">{mission.title}</h3>

        {mission.description && (
          <p className="mission-modal-desc">{mission.description}</p>
        )}

        {hasEntryPrice && (
          <p className="mission-modal-line">
            Вход: {mission.entryRoot} ROOT
          </p>
        )}

        {requiredItems.length > 0 && (
          <p className="mission-modal-line">
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
          <p className="mission-modal-line mission-modal-rewards">
            Возможные награды: {rewardLabels.join(', ')}
          </p>
        )}

        {error && (
          <ErrorWithCode message={error} className="mission-modal-error" />
        )}

        <div className="mission-modal-actions">
          <button
            onClick={onAccept}
            disabled={isAccepting}
            className="mission-modal-btn-accept"
          >
            {isAccepting
              ? 'ПОЛУЧЕНИЕ GPS…'
              : 'ВЗЯТЬ МИССИЮ'}
          </button>

          <button
            onClick={onClose}
            disabled={isAccepting}
            className="mission-modal-btn-cancel"
          >
            ОТМЕНА
          </button>
        </div>
      </div>
    </div>
  )
}
