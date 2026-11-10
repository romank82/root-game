import type { EngineMission } from '../api/engineApi'
import { useTranslation } from 'react-i18next'
import { ErrorWithCode } from './ErrorWithCode'
import { formatRootFromNano } from '../utils/formatRoot'

// Sprint 11.8 NanoROOT (этап 2C): 1 ROOT = 10^8 наноROOT.
// Fallback, если ответ пришёл без *_nano (legacy).
const NANO_PER_ROOT = 100_000_000

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
  const { t } = useTranslation(['terminal', 'common'])

  const hasEntryPrice =
    typeof mission.entryRoot === 'number' && mission.entryRoot > 0

  const requiredItems = mission.requiredItems ?? []

  const rewardLabels = (mission.rewards ?? [])
    .map((reward) => {
      if (reward.type === 'currency' && typeof reward.amount === 'number') {
        return t('terminal:rewards.currency', { amount: reward.amount })
      }
      if (reward.type === 'item' && reward.itemId) {
        return t('terminal:rewards.item', {
          name: reward.itemCode ?? reward.itemId,
        })
      }
      if (reward.type === 'story_node' && reward.storyNodeId) {
        return t('terminal:rewards.storyNode', { name: reward.storyNodeId })
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
        <p className="mission-modal-eyebrow">{t('terminal:missionModal.eyebrow')}</p>

        <h3 className="mission-modal-title">{mission.title}</h3>

        {mission.description && (
          <p className="mission-modal-desc">{mission.description}</p>
        )}

        {hasEntryPrice && (
          <p className="mission-modal-line">
            {t('terminal:missionModal.entryLabel')}{' '}
            {formatRootFromNano(
              mission.entryRootNano ?? (mission.entryRoot ?? 0) * NANO_PER_ROOT,
            )}{' '}
            ROOT
          </p>
        )}

        {requiredItems.length > 0 && (
          <p className="mission-modal-line">
            {t('terminal:missionModal.requiredKeysLabel')}{' '}
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
            {t('terminal:missionModal.rewardsLabel')} {rewardLabels.join(', ')}
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
              ? t('terminal:missionModal.acceptLoading')
              : t('terminal:missionModal.accept')}
          </button>

          <button
            onClick={onClose}
            disabled={isAccepting}
            className="mission-modal-btn-cancel"
          >
            {t('common:cancel')}
          </button>
        </div>
      </div>
    </div>
  )
}
