import type { EngineStoryNode } from '../../api/engineApi'
import type { Screen } from '../../types/game'

interface ArchiveScreenProps {
  storyNodes: EngineStoryNode[]
  onScreenChange: (screen: Screen) => void
}

export function ArchiveScreen({
  storyNodes,
  onScreenChange,
}: ArchiveScreenProps) {
  return (
    <section className="archive">
      <p className="eyebrow">АРХИВ / ЛИЧНЫЙ ДОСТУП</p>
      <h2>Полученные фрагменты</h2>

      {storyNodes.length === 0 ? (
        <div className="locked-file">
          <span>?</span>
          <div>
            <strong>АРХИВ ПОКА ПУСТ</strong>
            <small>
              Сюжетные фрагменты появятся здесь только после server-confirmed
              разблокировки.
            </small>
          </div>
        </div>
      ) : (
        storyNodes.map((storyNode) => (
          <article
            className="message-card archive-story-node"
            key={storyNode.id}
          >
            <span className="file-label">
              СЕРВЕРНЫЙ СЮЖЕТНЫЙ ФРАГМЕНТ
            </span>
            <h3>{storyNode.title}</h3>
            <p>{storyNode.body}</p>
            <small>СТАТУС: РАЗБЛОКИРОВАН BACKEND-СЕРВЕРОМ</small>
          </article>
        ))
      )}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}
