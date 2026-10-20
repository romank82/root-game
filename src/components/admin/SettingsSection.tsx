import { useEffect, useMemo, useState } from 'react'
import {
  listSystemSettings,
  updateSystemSetting,
  type AdminSystemSetting,
  type AdminUser,
} from '../../api/adminApi'

type SettingsSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

export function SettingsSection({
  admin,
  canWrite: _canWrite,
  onError: _onError,
  onNotice: _onNotice,
}: SettingsSectionProps) {
  const [settings, setSettings] = useState<AdminSystemSetting[]>([])
  const [selectedSettingKey, setSelectedSettingKey] = useState<string | null>(
    null,
  )
  const [loadingSettings, setLoadingSettings] = useState(false)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingDraft, setSettingDraft] = useState<string>('')
  const [settingReason, setSettingReason] = useState<string>('')
  const [savingSetting, setSavingSetting] = useState(false)
  const [savingError, setSavingError] = useState<string | null>(null)
  const [savingNotice, setSavingNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadingSettings(true)
    setSettingsError(null)
    listSystemSettings()
      .then((data) => {
        if (cancelled) return
        setSettings(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSettingsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingSettings(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedSettingKey !== null) return
    if (settings.length === 0) return
    setSelectedSettingKey(settings[0].key)
  }, [settings, selectedSettingKey])

  useEffect(() => {
    if (selectedSettingKey === null) {
      setSettingDraft('')
      setSettingReason('')
      setSavingError(null)
      setSavingNotice(null)
      return
    }
    const s = settings.find((x) => x.key === selectedSettingKey)
    if (!s) return
    if (s.valueType === 'boolean') {
      setSettingDraft(s.value === true ? 'true' : 'false')
    } else if (s.valueType === 'integer') {
      setSettingDraft(String(s.value ?? 0))
    } else if (s.valueType === 'string') {
      setSettingDraft(typeof s.value === 'string' ? s.value : '')
    } else {
      setSettingDraft(JSON.stringify(s.value, null, 2))
    }
    setSettingReason('')
    setSavingError(null)
    setSavingNotice(null)
  }, [selectedSettingKey, settings])

  const groupedSettings = useMemo(() => {
    const groups = new Map<string, AdminSystemSetting[]>()
    for (const s of settings) {
      const arr = groups.get(s.category) ?? []
      arr.push(s)
      groups.set(s.category, arr)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [settings])

  function selectedSetting(): AdminSystemSetting | null {
    if (selectedSettingKey === null) return null
    return settings.find((s) => s.key === selectedSettingKey) ?? null
  }

  async function handleSaveSetting() {
    const s = selectedSetting()
    if (!s) return
    if (s.isSensitive && !(admin?.isSuperAdmin ?? false)) {
      setSavingError(
        'Чувствительные настройки нельзя менять напрямую — требуется approval супер-админа.',
      )
      return
    }
    let parsed: unknown
    if (s.valueType === 'boolean') {
      parsed = settingDraft === 'true'
    } else if (s.valueType === 'integer') {
      const n = Number.parseInt(settingDraft, 10)
      if (!Number.isFinite(n) || n < 0) {
        setSavingError('Значение должно быть неотрицательным целым числом.')
        return
      }
      parsed = n
    } else if (s.valueType === 'string') {
      parsed = settingDraft
    } else {
      try {
        parsed = JSON.parse(settingDraft)
      } catch {
        setSavingError('Значение — невалидный JSON.')
        return
      }
    }
    setSavingSetting(true)
    setSavingError(null)
    setSavingNotice(null)
    try {
      const updated = await updateSystemSetting(
        s.key,
        parsed,
        settingReason.trim() || undefined,
      )
      setSettings((prev) =>
        prev.map((x) => (x.key === updated.key ? updated : x)),
      )
      setSavingNotice('Сохранено.')
    } catch (err) {
      setSavingError((err as Error).message)
    } finally {
      setSavingSetting(false)
    }
  }

  return (
        <div className="admin-layout admin-settings-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedSettingKey(null)
                setSettings([])
                setSettingsError(null)
                setLoadingSettings(true)
                listSystemSettings()
                  .then(setSettings)
                  .catch((err: Error) => setSettingsError(err.message))
                  .finally(() => setLoadingSettings(false))
              }}
              disabled={loadingSettings}
            >
              {loadingSettings ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {settingsError && (
              <p className="admin-alert admin-error">{settingsError}</p>
            )}

            <div className="admin-mission-list">
              {groupedSettings.map(([category, items]) => (
                <div key={category}>
                  <p className="admin-category-label">{category}</p>
                  {items.map((s) => (
                    <button
                      className={`admin-mission-row ${selectedSettingKey === s.key ? 'is-active' : ''}`}
                      key={s.key}
                      onClick={() => setSelectedSettingKey(s.key)}
                    >
                      {s.isSensitive && (
                        <span className="admin-badge admin-badge-sensitive">
                          sensitive
                        </span>
                      )}
                      <strong>{s.title}</strong>
                      <small>{s.key}</small>
                    </button>
                  ))}
                </div>
              ))}
              {!loadingSettings && settings.length === 0 && !settingsError && (
                <p className="admin-muted">Настроек нет.</p>
              )}
            </div>
          </aside>

          <section className="admin-editor">
            {selectedSetting() === null ? (
              <p className="admin-muted">Выберите настройку слева.</p>
            ) : (
              (() => {
                const s = selectedSetting()!
                const canEditSetting = !s.isSensitive || (admin?.isSuperAdmin ?? false)
                return (
                  <>
                    <div className="admin-editor-title">
                      <h2>{s.title}</h2>
                      {s.isSensitive && (
                        <span className="admin-badge admin-badge-sensitive">
                          sensitive
                          {admin?.isSuperAdmin ? ' · изменение напрямую' : ' · только через approval'}
                        </span>
                      )}
                    </div>

                    {s.description && (
                      <p className="admin-muted">{s.description}</p>
                    )}

                    <p className="admin-muted">
                      <b>Ключ:</b> <code>{s.key}</code>
                    </p>
                    <p className="admin-muted">
                      <b>Категория:</b> {s.category} · <b>Тип:</b> {s.valueType}
                    </p>

                    {savingError && (
                      <p className="admin-alert admin-error">{savingError}</p>
                    )}
                    {savingNotice && (
                      <p className="admin-alert admin-notice">{savingNotice}</p>
                    )}

                    <label className="admin-field">
                      <span>
                        Значение
                        {s.valueType === 'json' && ' (JSON)'}
                      </span>
                      {s.valueType === 'boolean' ? (
                        <input
                          type="checkbox"
                          checked={settingDraft === 'true'}
                          onChange={(e) => setSettingDraft(e.target.checked ? 'true' : 'false')}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.valueType === 'integer' ? (
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.valueType === 'string' ? (
                        <input
                          type="text"
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.key === 'missions.default_attempt_reward_multipliers' ? (
                        (() => {
                          // Парсим draft в массив долей 0..1.
                          let multipliers: number[] = []
                          try {
                            const parsed = JSON.parse(settingDraft)
                            if (Array.isArray(parsed)) {
                              multipliers = parsed.map(Number)
                            }
                          } catch {
                            multipliers = []
                          }
                          if (multipliers.length === 0) multipliers = [1.0]

                          const updateMultipliers = (next: number[]) => {
                            setSettingDraft(JSON.stringify(next))
                          }

                          return (
                            <div className="admin-multipliers">
                              {multipliers.map((value, idx) => (
                                <div className="admin-multiplier-row" key={idx}>
                                  <span className="admin-multiplier-label">
                                    Попытка {idx + 1}
                                  </span>
                                  <input
                                    type="number"
                                    min={0}
                                    max={100}
                                    step={1}
                                    value={Math.round(value * 100)}
                                    onChange={(e) => {
                                      const pct = Number.parseInt(e.target.value, 10)
                                      if (!Number.isFinite(pct)) return
                                      const next = [...multipliers]
                                      next[idx] = Math.max(0, Math.min(100, pct)) / 100
                                      updateMultipliers(next)
                                    }}
                                    disabled={!canEditSetting || savingSetting}
                                  />
                                  <span className="admin-multiplier-percent">%</span>
                                  {idx > 0 && (
                                    <button
                                      type="button"
                                      className="admin-multiplier-remove"
                                      onClick={() => {
                                        const next = multipliers.filter((_, i) => i !== idx)
                                        updateMultipliers(next.length > 0 ? next : [1.0])
                                      }}
                                      disabled={!canEditSetting || savingSetting}
                                    >
                                      ×
                                    </button>
                                  )}
                                </div>
                              ))}
                              {multipliers.length < 10 && (
                                <button
                                  type="button"
                                  className="admin-multiplier-add"
                                  onClick={() => {
                                    const last = multipliers[multipliers.length - 1] ?? 1.0
                                    const next = Math.max(0, last / 2)
                                    updateMultipliers([...multipliers, next])
                                  }}
                                  disabled={!canEditSetting || savingSetting}
                                >
                                  + Добавить попытку
                                </button>
                              )}
                            </div>
                          )
                        })()
                      ) : (
                        <textarea
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          rows={6}
                          disabled={!canEditSetting || savingSetting}
                        />
                      )}
                    </label>

                    <label className="admin-field">
                      <span>Причина (для аудита, необязательно)</span>
                      <input
                        type="text"
                        value={settingReason}
                        onChange={(e) => setSettingReason(e.target.value)}
                        disabled={!canEditSetting || savingSetting}
                        maxLength={200}
                      />
                    </label>

                    <div className="admin-actions">
                      <button
                        className="admin-primary"
                        onClick={handleSaveSetting}
                        disabled={!canEditSetting || savingSetting}
                      >
                        {savingSetting ? 'Сохранение…' : 'Сохранить'}
                      </button>
                    </div>
                  </>
                )
              })()
            )}
          </section>
        </div>
  )
}
