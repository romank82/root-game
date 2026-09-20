import type { EngineMission, EngineStoryNode } from '../../api/engineApi'
import type { Screen } from '../../types/game'

interface ArchiveScreenProps {
  missions: EngineMission[]
  storyNodes: EngineStoryNode[]
  onScreenChange: (screen: Screen) => void
}

export function ArchiveScreen({ missions, storyNodes, onScreenChange }: ArchiveScreenProps) {
  const secondSolved = missions.some(
    (mission) =>
      mission.id === 'mission-puzzle-a-02' &&
      mission.status === 'completed',
  )

  const storyNodeA17 = storyNodes.find(
    (storyNode) => storyNode.id === 'story-node-a17',
  )

  return (
    <section className="archive">
      <p className="eyebrow">АРХИВ / УРОВЕНЬ ДОСТУПА: 01</p>

      <h2>Полученные фрагменты</h2>

      <button
        className="archive-file"
        onClick={() => onScreenChange('terminal')}
      >
        <span>TXT</span>

        <div>
          <strong>ФРАГМЕНТ A-01</strong>
          <small>Получен во время инициализации контура</small>
        </div>

        <b>ОТКРЫТЬ →</b>
      </button>

      {secondSolved ? (
        <button
          className="archive-file"
          onClick={() => onScreenChange('terminal')}
        >
          <span>LOG</span>

          <div>
            <strong>ФРАГМЕНТ A-02</strong>
            <small>Восстановленный журнал архивного узла</small>
          </div>

          <b>ОТКРЫТЬ →</b>
        </button>
      ) : (
        <div className="locked-file">
          <span>?</span>

          <div>
            <strong>НЕИЗВЕСТНЫЙ ФРАГМЕНТ</strong>
            <small>Требуется расшифровка пакета A-01</small>
          </div>
        </div>
      )}

      {storyNodeA17 && (
        <article className="message-card archive-story-node">
          <span className="file-label">СЕРВЕРНЫЙ СЮЖЕТНЫЙ ФРАГМЕНТ</span>
          <h3>{storyNodeA17.title}</h3>
          <p>{storyNodeA17.body}</p>
          <small>СТАТУС: РАЗБЛОКИРОВАН BACKEND-СЕРВЕРОМ</small>
        </article>
      )}
    </section>
  )
}
