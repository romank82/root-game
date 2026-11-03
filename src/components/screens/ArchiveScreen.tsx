import type { EngineStoryNode } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { useTranslation } from 'react-i18next'

interface ArchiveScreenProps {
  storyNodes: EngineStoryNode[]
  onScreenChange: (screen: Screen) => void
}

export function ArchiveScreen({
  storyNodes,
  onScreenChange,
}: ArchiveScreenProps) {
  const { t } = useTranslation(['archive', 'common'])
  return (
    <section className="archive">
      <p className="eyebrow">{t('archive:header.eyebrow')}</p>
      <h2>{t('archive:header.title')}</h2>

      {storyNodes.length === 0 ? (
        <div className="locked-file">
          <span>?</span>
          <div>
            <strong>{t('archive:empty.title')}</strong>
            <small>{t('archive:empty.body')}</small>
          </div>
        </div>
      ) : (
        storyNodes.map((storyNode) => (
          <article
            className="message-card archive-story-node"
            key={storyNode.id}
          >
            <span className="file-label">{t('archive:card.label')}</span>
            <h3>{storyNode.title}</h3>
            <p>{storyNode.body}</p>
            <small>{t('archive:card.status')}</small>
          </article>
        ))
      )}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        {t('common:backToContour')}
      </button>
    </section>
  )
}
