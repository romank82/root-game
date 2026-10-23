import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  getMyProfile,
  saveMyProfile,
  type MyProfile,
  type MyProfilePayload,
} from '../../api/engineApi'

interface ProfileScreenProps {
  onScreenChange: (screen: Screen) => void
}

// Черновик анкеты: age хранится строкой (инпут type="number"),
// в число парсится только при сохранении.
type DraftState = {
  country: string
  gender: string
  age: string
}

// Значения gender — контракт backend-схемы (admin_players.VALID_GENDERS):
// {"male", "female", "other", "unspecified"}.
const GENDER_OPTIONS: { value: string; label: string }[] = [
  { value: 'male', label: 'Мужской' },
  { value: 'female', label: 'Женский' },
  { value: 'other', label: 'Другое' },
  { value: 'unspecified', label: 'Не определился' },
]

function draftFromPlayer(player: MyProfile): DraftState {
  return {
    country: player.country ?? '',
    gender: player.gender ?? '',
    age: player.age === null ? '' : String(player.age),
  }
}

// Нормализация по PATCH-контракту: пустая строка → null,
// страна — trim().toUpperCase().
function buildPayload(draft: DraftState): MyProfilePayload {
  const country = draft.country.trim().toUpperCase()
  return {
    country: country === '' ? null : country,
    gender: draft.gender === '' ? null : draft.gender,
    age: draft.age === '' ? null : Number(draft.age),
  }
}

export function ProfileScreen({ onScreenChange }: ProfileScreenProps) {
  const [profile, setProfile] = useState<MyProfile | null>(null)
  const [draft, setDraft] = useState<DraftState>({
    country: '',
    gender: '',
    age: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getMyProfile()
      .then((data) => {
        if (cancelled) return
        setProfile(data.player)
        setDraft(draftFromPlayer(data.player))
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Черновик изменён, если нормализованные значения отличаются от
  // сохранённого профиля (для age пустая строка и null эквивалентны).
  function isDirty(): boolean {
    if (profile === null) return false
    const next = buildPayload(draft)
    return (
      (next.country ?? '') !== (profile.country ?? '') ||
      (next.gender ?? '') !== (profile.gender ?? '') ||
      (next.age ?? null) !== (profile.age ?? null)
    )
  }

  function handleCancel() {
    if (profile === null) return
    setError(null)
    setDraft(draftFromPlayer(profile))
  }

  async function handleSave() {
    if (profile === null || saving) return
    setSaving(true)
    setError(null)
    try {
      const result = await saveMyProfile(buildPayload(draft))
      setProfile(result.player)
      setDraft(draftFromPlayer(result.player))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="inventory">
      <p className="eyebrow">ПРОФИЛЬ / АНКЕТА ИГРОКА</p>
      <h2>Профиль</h2>

      {loading && <p>Загрузка…</p>}
      {error && <p className="repair-error">{error}</p>}

      {!loading && profile && (
        <>
          <p>
            Игрок: <b>{profile.nickname}</b>
          </p>

          <label>
            Страна (ISO-код, 2 символа)
            <input
              type="text"
              maxLength={2}
              value={draft.country}
              onChange={(e) => setDraft({ ...draft, country: e.target.value })}
            />
          </label>

          <label>
            Пол
            <select
              value={draft.gender}
              onChange={(e) => setDraft({ ...draft, gender: e.target.value })}
            >
              <option value="">Не указан</option>
              {GENDER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            Возраст
            <input
              type="number"
              min={0}
              max={120}
              value={draft.age}
              onChange={(e) => setDraft({ ...draft, age: e.target.value })}
            />
          </label>

          <button
            type="button"
            className="primary-button"
            disabled={!isDirty() || saving}
            onClick={handleSave}
          >
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>

          <button type="button" onClick={handleCancel}>
            Отмена
          </button>
        </>
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