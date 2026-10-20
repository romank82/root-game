import { useEffect, useState } from 'react'
import {
  createKeyItem,
  listKeyRules,
  updateKeyRule,
  type AdminUser,
  type KeyItem,
  type KeyRule,
} from '../../api/adminApi'

type KeysSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  keyItems: KeyItem[]
}

export function KeysSection({
  admin: _admin,
  canWrite: _canWrite,
  onError: _onError,
  onNotice: _onNotice,
  keyItems: _keyItems,
}: KeysSectionProps) {
  const [keyRules, setKeyRules] = useState<KeyRule[]>([])
  const [selectedKeyRuleId, setSelectedKeyRuleId] = useState<string | null>(null)
  const [loadingKeyRules, setLoadingKeyRules] = useState(false)
  const [keyRulesError, setKeyRulesError] = useState<string | null>(null)
  const [showCreateKey, setShowCreateKey] = useState(false)
  const [newKeyTitle, setNewKeyTitle] = useState('')
  const [newKeyCode, setNewKeyCode] = useState('')
  const [newKeySymbol, setNewKeySymbol] = useState('')
  const [newKeyConsumable, setNewKeyConsumable] = useState(true)
  const [newKeyPrice, setNewKeyPrice] = useState('')
  const [creatingKey, setCreatingKey] = useState(false)
  const [createKeyError, setCreateKeyError] = useState<string | null>(null)
  const [keyEditConsumable, setKeyEditConsumable] = useState(false)
  const [keyEditPrice, setKeyEditPrice] = useState('')
  const [keyEditSortOrder, setKeyEditSortOrder] = useState('0')
  const [keyEditTransferForbidden, setKeyEditTransferForbidden] = useState(true)
  const [keyEditSaleForbidden, setKeyEditSaleForbidden] = useState(true)
  const [keyEditTradeForbidden, setKeyEditTradeForbidden] = useState(true)
  const [savingKey, setSavingKey] = useState(false)
  const [savingKeyError, setSavingKeyError] = useState<string | null>(null)
  const [savingKeyNotice, setSavingKeyNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadingKeyRules(true)
    setKeyRulesError(null)
    listKeyRules()
      .then((data) => {
        if (cancelled) return
        setKeyRules(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setKeyRulesError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingKeyRules(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setShowCreateKey(false)
    setCreateKeyError(null)
  }, [selectedKeyRuleId])

  useEffect(() => {
    const k = selectedKeyRule()
    if (!k) {
      setSavingKeyError(null)
      setSavingKeyNotice(null)
      return
    }
    setKeyEditConsumable(k.isConsumable)
    setKeyEditPrice(k.price != null ? String(k.price) : '')
    setKeyEditSortOrder(String(k.sortOrder))
    setKeyEditTransferForbidden(k.transferForbidden)
    setKeyEditSaleForbidden(k.saleForbidden)
    setKeyEditTradeForbidden(k.tradeForbidden)
    setSavingKeyError(null)
    setSavingKeyNotice(null)
  }, [selectedKeyRuleId, keyRules])

  function selectedKeyRule(): KeyRule | null {
    if (selectedKeyRuleId === null) return null
    return keyRules.find((k) => k.id === selectedKeyRuleId) ?? null
  }

  async function handleCreateKey() {
    const title = newKeyTitle.trim()
    const code = newKeyCode.trim().toUpperCase().replace(/\s+/g, '_')
    if (title.length < 1) {
      setCreateKeyError('Название ключа обязательно.')
      return
    }
    if (code.length < 1) {
      setCreateKeyError('Код ключа обязателен (латиница, цифры, _).')
      return
    }
    const price = newKeyPrice.trim() ? Number.parseInt(newKeyPrice, 10) : null
    if (price !== null && (!Number.isFinite(price) || price < 1)) {
      setCreateKeyError('Цена должна быть целым числом ≥ 1 (пусто = глобальная).')
      return
    }
    setCreatingKey(true)
    setCreateKeyError(null)
    try {
      const created = await createKeyItem({
        title,
        code,
        symbol: newKeySymbol.trim() || null,
        is_consumable: newKeyConsumable,
        price,
      })
      setKeyRules((prev) => [...prev, created])
      setSelectedKeyRuleId(created.id)
      setShowCreateKey(false)
      setNewKeyTitle('')
      setNewKeyCode('')
      setNewKeySymbol('')
      setNewKeyConsumable(true)
      setNewKeyPrice('')
    } catch (err) {
      setCreateKeyError((err as Error).message)
    } finally {
      setCreatingKey(false)
    }
  }

  async function handleSaveKey() {
    const k = selectedKeyRule()
    if (!k) return
    const price = keyEditPrice.trim() ? Number.parseInt(keyEditPrice, 10) : null
    if (price !== null && (!Number.isFinite(price) || price < 1)) {
      setSavingKeyError('Цена должна быть целым числом ≥ 1 (пусто = глобальная).')
      return
    }
    const sortOrder = Number.parseInt(keyEditSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      setSavingKeyError('Порядок должен быть неотрицательным целым.')
      return
    }
    setSavingKey(true)
    setSavingKeyError(null)
    setSavingKeyNotice(null)
    try {
      const updated = await updateKeyRule(k.id, {
        is_consumable: keyEditConsumable,
        price,
        sort_order: sortOrder,
        transfer_forbidden: keyEditTransferForbidden,
        sale_forbidden: keyEditSaleForbidden,
        trade_forbidden: keyEditTradeForbidden,
      })
      setKeyRules((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
      setSavingKeyNotice('Сохранено.')
    } catch (err) {
      setSavingKeyError((err as Error).message)
    } finally {
      setSavingKey(false)
    }
  }

  return (
        <div className="admin-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-primary"
              onClick={() => {
                setShowCreateKey(true)
                setCreateKeyError(null)
                setNewKeyTitle('')
                setNewKeyCode('')
                setNewKeySymbol('')
                setNewKeyConsumable(true)
                setNewKeyPrice('')
              }}
            >
              + Новый ключ
            </button>
            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedKeyRuleId(null)
                setKeyRules([])
                setKeyRulesError(null)
                setLoadingKeyRules(true)
                listKeyRules()
                  .then(setKeyRules)
                  .catch((err: Error) => setKeyRulesError(err.message))
                  .finally(() => setLoadingKeyRules(false))
              }}
              disabled={loadingKeyRules}
            >
              {loadingKeyRules ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {keyRulesError && (
              <p className="admin-alert admin-error">{keyRulesError}</p>
            )}

            <div className="admin-mission-list">
              {keyRules.map((k) => (
                <button
                  className={`admin-mission-row ${selectedKeyRuleId === k.id ? 'is-active' : ''}`}
                  key={k.id}
                  onClick={() => setSelectedKeyRuleId(k.id)}
                >
                  {k.itemSymbol && (
                    <span className="admin-key-symbol">{k.itemSymbol}</span>
                  )}
                  {k.isConsumable && (
                    <span className="admin-badge admin-badge-consumable">
                      расходуемый
                    </span>
                  )}
                  <strong>{k.itemTitle}</strong>
                  <small>{k.itemCode}</small>
                </button>
              ))}
              {!loadingKeyRules && keyRules.length === 0 && !keyRulesError && (
                <p className="admin-muted">Ключей нет.</p>
              )}
            </div>
          </aside>

          <section className="admin-editor">
            {showCreateKey ? (
              <>
                <div className="admin-editor-title">
                  <h2>Новый ключ</h2>
                </div>

                {createKeyError && (
                  <p className="admin-alert admin-error">{createKeyError}</p>
                )}

                <label className="admin-field">
                  <span>Название (например, «КЛЮЧ B-02»)</span>
                  <input
                    type="text"
                    value={newKeyTitle}
                    onChange={(e) => setNewKeyTitle(e.target.value)}
                    maxLength={255}
                    disabled={creatingKey}
                  />
                </label>

                <label className="admin-field">
                  <span>Код (латиница, цифры, _ — например KEY_B02)</span>
                  <input
                    type="text"
                    value={newKeyCode}
                    onChange={(e) => setNewKeyCode(e.target.value)}
                    maxLength={128}
                    disabled={creatingKey}
                  />
                </label>

                <label className="admin-field">
                  <span>Символ (необязательно, 1 эмодзи)</span>
                  <input
                    type="text"
                    value={newKeySymbol}
                    onChange={(e) => setNewKeySymbol(e.target.value)}
                    maxLength={32}
                    disabled={creatingKey}
                  />
                </label>

                <label className="admin-field">
                  <span>
                    <input
                      type="checkbox"
                      checked={newKeyConsumable}
                      onChange={(e) => setNewKeyConsumable(e.target.checked)}
                      disabled={creatingKey}
                    />{' '}
                    Расходуется при использовании
                  </span>
                </label>

                <label className="admin-field">
                  <span>Цена (ROOT) — пусто = глобальная настройка</span>
                  <input
                    type="number"
                    min={1}
                    value={newKeyPrice}
                    onChange={(e) => setNewKeyPrice(e.target.value)}
                    placeholder="Пусто = глобальная настройка"
                    disabled={creatingKey}
                  />
                </label>

                <div className="admin-actions">
                  <button
                    className="admin-primary"
                    onClick={handleCreateKey}
                    disabled={creatingKey}
                  >
                    {creatingKey ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateKey(false)}
                    disabled={creatingKey}
                  >
                    Отмена
                  </button>
                </div>

                <p className="admin-muted" style={{ marginTop: 24 }}>
                  Ключ будет опубликован и сразу появится в выборе наград для
                  миссий.
                </p>
              </>
            ) : selectedKeyRule() === null ? (
              <p className="admin-muted">Выберите ключ слева.</p>
            ) : (
              (() => {
                const k = selectedKeyRule()!
                return (
                  <>
                    <div className="admin-editor-title">
                      <h2>{k.itemTitle}</h2>
                      {k.isConsumable && (
                        <span className="admin-badge admin-badge-consumable">
                          расходуемый
                        </span>
                      )}
                      {!k.isConsumable && (
                        <span className="admin-badge">постоянный</span>
                      )}
                    </div>

                    <p className="admin-muted">
                      <b>Код:</b>{' '}
                      <code>{k.itemCode}</code> · <b>Item ID:</b>{' '}
                      <code>{k.itemId}</code>
                    </p>
                    <p className="admin-muted">
                      <b>Статус:</b> {k.itemStatus}
                    </p>

                    {savingKeyError && (
                      <p className="admin-alert admin-error">
                        {savingKeyError}
                      </p>
                    )}
                    {savingKeyNotice && (
                      <p className="admin-alert admin-notice">
                        {savingKeyNotice}
                      </p>
                    )}

                    <h3 style={{ marginTop: 24 }}>Правила</h3>

                    <label className="admin-field">
                      <span>
                        <input
                          type="checkbox"
                          checked={keyEditConsumable}
                          onChange={(e) =>
                            setKeyEditConsumable(e.target.checked)
                          }
                          disabled={savingKey}
                        />{' '}
                        Расходуется при использовании
                      </span>
                    </label>

                    <label className="admin-field">
                      <span>Цена (ROOT) — пусто = глобальная настройка</span>
                      <input
                        type="number"
                        min={1}
                        value={keyEditPrice}
                        onChange={(e) => setKeyEditPrice(e.target.value)}
                        placeholder="Пусто = глобальная настройка"
                        disabled={savingKey}
                      />
                    </label>

                    <label className="admin-field">
                      <span>
                        Порядок отображения (меньше = выше в списке)
                      </span>
                      <input
                        type="number"
                        min={0}
                        value={keyEditSortOrder}
                        onChange={(e) => setKeyEditSortOrder(e.target.value)}
                        disabled={savingKey}
                      />
                    </label>

                    <h3 style={{ marginTop: 24 }}>Запреты</h3>

                    <label className="admin-field">
                      <span>
                        <input
                          type="checkbox"
                          checked={keyEditTransferForbidden}
                          onChange={(e) =>
                            setKeyEditTransferForbidden(e.target.checked)
                          }
                          disabled={savingKey}
                        />{' '}
                        Запретить передачу другим игрокам
                      </span>
                    </label>

                    <label className="admin-field">
                      <span>
                        <input
                          type="checkbox"
                          checked={keyEditSaleForbidden}
                          onChange={(e) =>
                            setKeyEditSaleForbidden(e.target.checked)
                          }
                          disabled={savingKey}
                        />{' '}
                        Запретить продажу
                      </span>
                    </label>

                    <label className="admin-field">
                      <span>
                        <input
                          type="checkbox"
                          checked={keyEditTradeForbidden}
                          onChange={(e) =>
                            setKeyEditTradeForbidden(e.target.checked)
                          }
                          disabled={savingKey}
                        />{' '}
                        Запретить обмен
                      </span>
                    </label>

                    <div className="admin-actions" style={{ marginTop: 16 }}>
                      <button
                        className="admin-primary"
                        onClick={handleSaveKey}
                        disabled={savingKey}
                      >
                        {savingKey ? 'Сохранение…' : 'Сохранить'}
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
