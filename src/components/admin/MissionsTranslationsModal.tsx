import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  getMissionTranslations,
  putMissionTranslations,
  type MissionTranslation,
  type MissionTranslationsResponse,
  type MissionTranslationStatus,
} from '../../api/adminApi'
import {
  mergeParsedFields,
  normalizeBlocks,
  parseNumbered,
} from '../../utils/missionTranslationParse'

type Props = {
  missionId: string
  missionTitle: string
  // Оригинал контента миссии (RU) для поля «Текущий текст — для перевода».
  // Берётся из AdminMission (title/description/content), а не из draft перевода.
  missionDescription: string | null
  missionContentUi: Record<string, string | string[]>
  onClose: () => void
  onSaved: (status: MissionTranslationStatus) => void
}

type Draft = Record<string, MissionTranslation>

// Базовый язык контента: оригинал в mission.title/description; переводы на
// него не требуются (совпадает с BASE_CONTENT_LANGUAGE на бэке, Trans-2b-2).
const BASE_LANGUAGE = 'ru'

const LANGUAGE_LABELS: Record<string, string> = {
  ru: 'Русский',
  en: 'English',
  zh: '中文',
}

const FIELD_LABELS: Record<string, string> = {
  title: 'Название',
  description: 'Описание',
  blocks: 'Блоки (JSON-массив строк)',
}

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field
}

function fieldValue(
  translation: MissionTranslation | undefined,
  field: string,
): string {
  if (field === 'title') {
    return translation?.title ?? ''
  }
  if (field === 'description') {
    return translation?.description ?? ''
  }
  const value = translation?.contentUi?.[field]
  return Array.isArray(value) ? JSON.stringify(value) : (value ?? '')
}

// Значение поля оригинального контента миссии (RU) для buildCopyText().
function originalFieldValue(
  title: string,
  description: string | null,
  contentUi: Record<string, string | string[]>,
  field: string,
): string {
  if (field === 'title') {
    return title
  }
  if (field === 'description') {
    return description ?? ''
  }
  const value = contentUi[field]
  return Array.isArray(value) ? JSON.stringify(value) : (value ?? '')
}

export function MissionsTranslationsModal({
  missionId,
  missionTitle,
  missionDescription,
  missionContentUi,
  onClose,
  onSaved,
}: Props) {
  const [data, setData] = useState<MissionTranslationsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [activeLang, setActiveLang] = useState(BASE_LANGUAGE)
  const [draft, setDraft] = useState<Draft>({})
  const [pasteText, setPasteText] = useState('')
  // code_repair.blocks редактируются как JSON-строка: промежуточный невалидный
  // JSON не должен затирать поле, поэтому парсим его при сохранении.
  const [blocksText, setBlocksText] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')

    getMissionTranslations(missionId)
      .then((response) => {
        if (cancelled) return
        const firstTarget =
          response.supportedLanguages.find((lang) => lang !== BASE_LANGUAGE) ??
          response.supportedLanguages[0] ??
          BASE_LANGUAGE
        setData(response)
        setDraft(response.translations || {})
        setActiveLang(firstTarget)
        setBlocksText(
          JSON.stringify(
            response.translations?.[firstTarget]?.contentUi?.blocks ?? [],
          ),
        )
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [missionId])

  const languages = data?.supportedLanguages ?? []
  const requiredUi = data?.requiredContentUiKeys ?? []
  const targetLangs = languages.filter((lang) => lang !== BASE_LANGUAGE)
  const fields = ['title', 'description', ...requiredUi]
  const current = draft[activeLang] || {}

  function isLangComplete(lang: string): boolean {
    const entry = draft[lang]
    if (!entry || !entry.title || !entry.description) {
      return false
    }
    const ui = entry.contentUi ?? {}
    return requiredUi.every((key) => {
      const value = ui[key]
      if (key === 'blocks') {
        return Array.isArray(value) && value.length > 0
      }
      return typeof value === 'string' && value.trim() !== ''
    })
  }

  function selectLanguage(lang: string) {
    setActiveLang(lang)
    setPasteText('')
    const blocks = draft[lang]?.contentUi?.blocks
    setBlocksText(Array.isArray(blocks) ? JSON.stringify(blocks) : '')
    setError('')
  }

  function buildCopyText(): string {
    // Источник — ОРИГИНАЛ (RU) из миссии, а не текущий draft перевода:
    // иначе в поле «Текущий текст» для новой миссии был бы пустой текст.
    return fields
      .map(
        (field, index) =>
          `[${index + 1}] ${originalFieldValue(missionTitle, missionDescription, missionContentUi, field)}`,
      )
      .join('\n')
  }

  function updateField(field: string, value: string) {
    if (field === 'blocks') {
      setBlocksText(value)
      const normalized = normalizeBlocks(value)
      setError(normalized.error ?? '')
      if (normalized.blocks === null) return
      const blocks = normalized.blocks
      setDraft((previous) => {
        const language: MissionTranslation = { ...(previous[activeLang] || {}) }
        const ui: MissionTranslation['contentUi'] = {
          ...(language.contentUi || {}),
        }
        ui.blocks = blocks
        language.contentUi = ui
        return { ...previous, [activeLang]: language }
      })
      return
    }

    setDraft((previous) => {
      const language: MissionTranslation = { ...(previous[activeLang] || {}) }
      if (field === 'title') {
        language.title = value
      } else if (field === 'description') {
        language.description = value
      } else {
        const ui: MissionTranslation['contentUi'] = {
          ...(language.contentUi || {}),
        }
        ui[field] = value
        language.contentUi = ui
      }
      return { ...previous, [activeLang]: language }
    })
  }

  function handlePaste(text: string) {
    const parsed = parseNumbered(text, fields.length)
    if (!parsed || parsed.every((value) => value === '')) {
      return
    }

    const blocksIndex = fields.indexOf('blocks')
    const blocksValue = blocksIndex >= 0 ? parsed[blocksIndex] : ''
    const normalizedBlocks =
      blocksValue === '' ? { blocks: [], error: null } : normalizeBlocks(blocksValue)
    if (normalizedBlocks.error !== null || normalizedBlocks.blocks === null) {
      setError(normalizedBlocks.error ?? 'Не удалось разобрать blocks.')
      return
    }
    const blocks = normalizedBlocks.blocks
    setDraft((previous) => {
      const base = previous[activeLang] || {}
      const merged = mergeParsedFields(
        base as Record<string, unknown>,
        parsed,
        fields,
      )
      if (merged === null) return previous

      const language = merged as MissionTranslation
      if (blocksValue !== '') {
        const ui: MissionTranslation['contentUi'] = {
          ...(language.contentUi || {}),
        }
        ui.blocks = blocks
        language.contentUi = ui
      }
      return { ...previous, [activeLang]: language }
    })

    if (blocksValue !== '') {
      setBlocksText(JSON.stringify(blocks))
    }
    setPasteText('')
  }

  async function handleSave() {
    const normalizedBlocks = fields.includes('blocks')
      ? normalizeBlocks(blocksText)
      : { blocks: [], error: null }
    if (normalizedBlocks.error !== null || normalizedBlocks.blocks === null) {
      setError(normalizedBlocks.error ?? 'Не удалось разобрать blocks.')
      return
    }
    const blocks = normalizedBlocks.blocks

    setSaving(true)
    setError('')

    // Применяем последний валидный JSON блоков к активному языку перед PUT.
    const finalDraft: Draft = { ...draft }
    if (fields.includes('blocks')) {
      const language: MissionTranslation = { ...(finalDraft[activeLang] || {}) }
      const ui: MissionTranslation['contentUi'] = {
        ...(language.contentUi || {}),
      }
      ui.blocks = blocks
      language.contentUi = ui
      finalDraft[activeLang] = language
    }

    try {
      const result = await putMissionTranslations(missionId, {
        translations: finalDraft,
      })
      onSaved(result.translationStatus)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  const content = (
    <div className="admin-modal-backdrop" onClick={onClose}>
      <div
        className="admin-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Перевод миссии ${missionTitle}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="admin-modal-header">
          <h3>Перевод: {missionTitle}</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {data && (
              <span className={`admin-modal-status is-${data.translationStatus}`}>
                {data.translationStatus}
              </span>
            )}
            <button
              type="button"
              className="admin-modal-close"
              onClick={onClose}
              aria-label="Закрыть"
            >
              ×
            </button>
          </div>
        </div>

        {loading && <p>Загрузка…</p>}
        {error && <p className="admin-alert admin-error">{error}</p>}

        {!loading && data && targetLangs.length === 0 && (
          <p className="admin-modal-note">
            В CMS нет языков перевода кроме русского (content.supported_languages).
            Добавьте язык в настройках системы.
          </p>
        )}

        {!loading && data && targetLangs.length > 0 && (
          <>
            <div className="admin-lang-tabs">
              {targetLangs.map((lang) => (
                <button
                  key={lang}
                  type="button"
                  className={`admin-lang-tab${activeLang === lang ? ' is-active' : ''}${isLangComplete(lang) ? ' is-complete' : ''}`}
                  onClick={() => selectLanguage(lang)}
                >
                  {LANGUAGE_LABELS[lang] || lang} {isLangComplete(lang) ? '✓' : '—'}
                </button>
              ))}
            </div>

            <div className="admin-modal-note">
              Русский — оригинал (не переводится). Формат копирования/вставки:{' '}
              <code>[1] Название</code>, <code>[2] Описание</code>, затем ключи{' '}
              <code>content.ui</code>.
            </div>

            <div className="admin-modal-field">
              <label>Текущий текст (ru) — для перевода:</label>
              <textarea
                readOnly
                value={buildCopyText()}
                onFocus={(event) => event.target.select()}
              />
            </div>

            <div className="admin-modal-field">
              <label>Вставьте перевод обратно ([1] текст, [2] текст, …):</label>
              <textarea
                value={pasteText}
                onChange={(event) => setPasteText(event.target.value)}
                placeholder={`[1] Название\n[2] Описание\n[3] ${requiredUi[0] ?? 'label'}`}
              />
              <button
                type="button"
                className="admin-secondary"
                onClick={() => handlePaste(pasteText)}
                disabled={pasteText.trim() === ''}
              >
                Применить
              </button>
            </div>

            {fields.map((field) => {
              const isBlocks = field === 'blocks'
              const value = isBlocks ? blocksText : fieldValue(current, field)
              const multiline = field === 'description' || isBlocks
              return (
                <div className="admin-modal-field" key={field}>
                  <label>{fieldLabel(field)}</label>
                  {multiline ? (
                    <textarea
                      value={value}
                      onChange={(event) => {
                        if (isBlocks) setBlocksText(event.target.value)
                        updateField(field, event.target.value)
                      }}
                    />
                  ) : (
                    <input
                      value={value}
                      onChange={(event) => updateField(field, event.target.value)}
                    />
                  )}
                </div>
              )
            })}

            <div className="admin-modal-actions">
              <button
                type="button"
                className="admin-secondary"
                onClick={onClose}
                disabled={saving}
              >
                Отмена
              </button>
              <button
                type="button"
                className="admin-primary"
                onClick={() => void handleSave()}
                disabled={saving}
              >
                {saving ? 'Сохранение…' : 'Сохранить'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )

  return createPortal(content, document.body)
}

