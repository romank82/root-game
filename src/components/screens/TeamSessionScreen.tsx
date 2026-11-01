import { useEffect, useRef, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  createTeamSession,
  getEngineBootstrap,
  getLastTeamSession,
  getTeamSessionMessages,
  getTeamSessions,
  joinTeamSession,
  markTeamSessionReady,
  sendTeamSessionMessage,
  submitTeamLocation,
  submitTeamWave,
  type EngineMission,
  type EngineTeamAwarded,
  type EngineTeamMessage,
  type EngineTeamSession,
} from '../../api/engineApi'
import { CipherGame } from '../CipherGame'

interface TeamSessionScreenProps {
  onScreenChange: (screen: Screen) => void
  // Командные миссии для формы создания (из App/bootstrap). Если не
  // переданы — экран сам сходит за bootstrap.
  missions?: EngineMission[]
  // Игрок пришёл с карты по клику на маркер миссии — предвыбор в форме.
  presetMissionId?: string | null
}

const TEAM_MISSION_LAYER = 'team'

const SESSION_STATUS_LABELS: Record<string, string> = {
  collecting: 'Сбор команды',
  ready_to_start: 'Все готовы — ожидание авто-старта',
  active: 'Игра идёт',
  succeeded: 'Успех',
  failed: 'Провал',
  expired: 'Истекла',
  cancelled_before_start: 'Отменена до старта',
}

function listTeamMissions(all: EngineMission[]): EngineMission[] {
  return all.filter((mission) => mission.missionLayer === TEAM_MISSION_LAYER)
}

// Sprint 6.6-b: время сообщения чата (ISO → ЧЧ:ММ локального времени).
function formatChatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function TeamSessionScreen({
  onScreenChange,
  missions,
  presetMissionId,
}: TeamSessionScreenProps) {
  // Активная сессия игрока (collecting/ready_to_start/active) или null.
  const [session, setSession] = useState<EngineTeamSession | null>(null)
  const [teamMissionsList, setTeamMissionsList] = useState<EngineMission[]>([])
  const [selectedMissionId, setSelectedMissionId] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // Sprint 8.x-4-join-gps: вступление в чужую сессию по её ID (GPS обязателен).
  const [joinSessionId, setJoinSessionId] = useState<string>('')
  const [joining, setJoining] = useState(false)
  const [readyBusy, setReadyBusy] = useState(false)
  // Sprint 8.x-4b-2a: состояние командной мини-игры (волна cipher).
  const [waveSubmitting, setWaveSubmitting] = useState(false)
  const [waveError, setWaveError] = useState<string | null>(null)
  const [waveSuccess, setWaveSuccess] = useState<string | null>(null)
  // Sprint 8.x-4-location-ui: отметка гео-присутствия (proof для активации).
  // locationBusy удалён в 8.x-4-ux-fix вместе с кнопкой (сообщения — текстом).
  const [locationNotice, setLocationNotice] = useState<string | null>(null)
  const [locationOk, setLocationOk] = useState(false)
  // Инкремент при смене волны/«ЗАНОВО» → CipherGame пересобирает барабаны/таймер.
  const [resetSignal, setResetSignal] = useState(0)
  // Ключ текущей волны для сравнения при polling (не сбрасывать игру
  // каждые 3 сек — только при реальной смене волны/кода).
  const prevWaveKeyRef = useRef<string | null>(null)
  // Sprint 8.x-4b-2b: отслеживание перехода waveStatus 'playing' → 'failed'
  // (алиас «Член команды провалил попытку»). Бэкенд меняет волну атомарно,
  // но контракт EngineTeamWaveStatus позволяет вошедшее в ответ/поллинг
  // значение 'failed' — на него показываем временную плашку (3 сек).
  const prevWaveStatusRef = useRef<string | null>(null)
  const [waveFailedNotice, setWaveFailedNotice] = useState<string | null>(null)
  // Итог командной мини-игры для финального экрана. Бэкенд /me отдаёт только
  // активные сессии — succeeded/failed приходит только в ответе submit-wave,
  // и на следующем поллинге сессия пропадает из /me (session становится null).
  const [finalStatus, setFinalStatus] = useState<'succeeded' | 'failed' | null>(
    null,
  )
  // Награды из ответа submit-wave (для финального экрана «МИССИЯ ПРОЙДЕНА»).
  const [lastAwarded, setLastAwarded] = useState<EngineTeamAwarded | null>(null)
  // Была ли у игрока активная сессия, которую поллинг потерял: после
  // финализации /me вернёт пустой список, и по этому флагу показываем
  // «Сессия завершена», а не форму создания (форма — только для тех, у кого
  // активных сессий вообще не было).
  const [sessionEnded, setSessionEnded] = useState(false)
  // Sprint 8.x-4-final-status-2: разовый флаг — /last зовём ОДИН раз после
  // того, как поллинг потерял сессию (иначе спам каждые 3 сек). Сбрасывается
  // при появлении новой активной сессии (polling useEffect).
  const finalFetchedRef = useRef(false)
  // Sprint 6.6-b: чат команды внутри сессии. Открыт только пока сессия в
  // collecting/ready_to_start/active — после финала бэкенд отдаёт 409.
  const [messages, setMessages] = useState<EngineTeamMessage[]>([])
  const [messagesHasMore, setMessagesHasMore] = useState(false)
  const [messagesBusy, setMessagesBusy] = useState(false)
  const [messageText, setMessageText] = useState('')
  const [sending, setSending] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [sessionsResult, bootstrap] = await Promise.all([
          getTeamSessions(),
          missions ? Promise.resolve(missions) : getEngineBootstrap(),
        ])

        if (cancelled) return

        const teamOnes = listTeamMissions(
          Array.isArray(bootstrap) ? bootstrap : bootstrap.missions,
        )
        setTeamMissionsList(teamOnes)

        // Бэкенд отдаёт только активные сессии игрока (одна на игрока).
        const active: EngineTeamSession | null =
          (sessionsResult.sessions[0] ?? null) as EngineTeamSession | null
        setSession(active)

        const preset = presetMissionId
        setSelectedMissionId(
          active
            ? active.mission_id
            : preset && teamOnes.some((m) => m.id === preset)
              ? preset
              : (teamOnes[0]?.id ?? ''),
        )
      } catch (err) {
        if (!cancelled) setError((err as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [missions, presetMissionId])

  // Sprint 8.x-4b-1: polling игрового состояния, пока сессия в статусе
  // 'active' (идёт мини-игра). Обновляет весь session-объект — новые поля
  // 8.x-3 (currentWave/maxWaves/waveStatus/wavePlayedCount/myWavePlayed/
  // cipherSession) уже лежат в типе EngineTeamSession. Вне 'active' и без
  // сессии опрос не нужен. UI мини-игры — шаг 8.x-4b-2.
  const sessionId = session?.id ?? null
  const sessionActive = session?.status === 'active'
  // Чат открыт только в активных статусах сессии (после финала — закрыт).
  const chatOpen =
    session !== null &&
    (session.status === 'collecting' ||
      session.status === 'ready_to_start' ||
      session.status === 'active')

  useEffect(() => {
    if (!sessionId || !sessionActive) return
    // Новая активная сессия — разовый флаг /last можно использовать снова.
    finalFetchedRef.current = false

    let cancelled = false
    let warnedOnce = false

    async function poll() {
      try {
        const result = await getTeamSessions()
        if (cancelled) return
        // Подхватываем и финализацию (succeeded/failed): сессия уходит из
        // ответа либо меняет status → setSession завершит этот эффект.
        setSession((result.sessions[0] ?? null) as EngineTeamSession | null)
        // Sprint 8.x-4b-2b: активная сессия исчезла из /me — финализация
        // кем-то из команды. Sprint 8.x-4-final-status-2: ОДИН раз дёргаем
        // /last — он отдаёт последнюю терминальную сессию (succeeded/failed)
        // с нашими наградами, чтобы финал увидели ВСЕ члены команды, а не
        // только последний отправивший.
        if (result.sessions.length === 0) {
          setSessionEnded(true)
          if (!finalFetchedRef.current) {
            finalFetchedRef.current = true
            void getLastTeamSession()
              .then((lastResult) => {
                if (cancelled) return
                if (lastResult.session) {
                  setFinalStatus(
                    lastResult.session.status === 'succeeded'
                      ? 'succeeded'
                      : 'failed',
                  )
                  setLastAwarded(lastResult.session.awarded ?? null)
                }
              })
              .catch(() => {
                // тихо: нейтральный «Сессия завершена» останется в стейте.
              })
          }
        }
      } catch {
        // Не спамить консоль каждые 3 сек: один warning, дальше пропускаем
        // опрос, последнее известное состояние остаётся в стейте.
        if (!cancelled && !warnedOnce) {
          warnedOnce = true
          console.warn('Не удалось обновить состояние командной сессии')
        }
      }
    }

    void poll()
    const interval = window.setInterval(() => void poll(), 3000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [sessionId, sessionActive])

  // Sprint 6.6-b: polling чата команды (3 сек, как у сессии). Работает только
  // пока сессия активна; при смене статуса на финальный — очищаем список и
  // останавливаем опрос (бэкенд после финала отдаёт 409).
  useEffect(() => {
    if (!chatOpen || sessionId === null) {
      setMessages([])
      setMessagesHasMore(false)
      return
    }
    const targetSessionId: string = sessionId
    let cancelled = false
    let warnedOnce = false

    async function pollMessages() {
      try {
        const result = await getTeamSessionMessages(targetSessionId, 50)
        if (cancelled) return
        setMessages(result.messages)
        setMessagesHasMore(result.hasMore)
      } catch {
        // Не спамить консоль каждые 3 сек: один warning, дальше тихо.
        if (!cancelled && !warnedOnce) {
          warnedOnce = true
          console.warn('Не удалось обновить чат командной сессии')
        }
      }
    }

    void pollMessages()
    const interval = window.setInterval(() => void pollMessages(), 3000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [chatOpen, sessionId])

  // Sprint 8.x-4-ux-fix: гео-присутствие отправляется АВТОМАТИЧЕСКИ один раз
  // после сбора команды, в ready_to_start (proof нужен бэкенду для активации).
  // Кнопка «ОТМЕТИТЬ ПРИСУТСТВИЕ» удалена — это был
  // костыль dev-проверки. proofSentRef ставится ДО вызова, чтобы polling
  // (getTeamSessions каждые 3 сек обновляет session) не спамил запросами.
  // Повтор при «вне зоны» — перезаход на экран (новый mount → новая попытка).
  const proofSentRef = useRef(false)

  useEffect(() => {
    if (proofSentRef.current) return
    if (!session) return
    if (session.status !== 'ready_to_start') {
      return
    }
    proofSentRef.current = true
    void handleSubmitLocation()
    // handleSubmitLocation — hoisted function declaration; вызов один раз
    // (proofSentRef), поэтому в deps достаточно session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session])

  // Sprint 8.x-4b-2a: пересборка CipherGame при смене волны/сессии (новые
  // барабаны и таймер) + сброс сообщений результата. Ключ — session.id +
  // currentWave + correctCode: polling пересоздаёт объект session каждые 3 сек,
  // но ключ стабилен, пока не сменилась волна (или код после провала) — сброс
  // НЕ на каждом опросе.
  const waveKey =
    session && session.status === 'active'
      ? `${session.id}:${session.currentWave}:${session.cipherSession?.correctCode?.join('') ?? 'none'}`
      : null

  useEffect(() => {
    if (waveKey === null) {
      prevWaveKeyRef.current = null
      return
    }
    if (prevWaveKeyRef.current === null) {
      prevWaveKeyRef.current = waveKey
      return
    }
    if (prevWaveKeyRef.current !== waveKey) {
      prevWaveKeyRef.current = waveKey
      setResetSignal((value) => value + 1)
      setWaveError(null)
      setWaveSuccess(null)
    }
  }, [waveKey])

  // Sprint 8.x-4b-2b: плашка «Член команды провалил попытку» — переход
  // waveStatus 'playing' → 'failed' (кто-то из команды ошибся на волне).
  // Вне активной сессии ref сбрасываем.
  const waveStatusValue = session?.waveStatus ?? null
  const waveStatusActive = session?.status === 'active'

  useEffect(() => {
    if (!waveStatusActive) {
      prevWaveStatusRef.current = null
      return
    }
    const previous = prevWaveStatusRef.current
    prevWaveStatusRef.current = waveStatusValue
    if (previous === 'playing' && waveStatusValue === 'failed') {
      setWaveFailedNotice(
        'Член команды провалил попытку. Переходим на следующую волну...',
      )
    }
  }, [waveStatusValue, waveStatusActive])

  // Плашка «член команды провалил» гаснет через 3 секунды (cleanup снимает
  // таймер, если за это время пришёл новый статус/размонтировался экран).
  useEffect(() => {
    if (waveFailedNotice === null) return
    const id = window.setTimeout(() => setWaveFailedNotice(null), 3000)
    return () => window.clearTimeout(id)
  }, [waveFailedNotice])

  async function handleCreate() {
    setError(null)
    setNotice(null)

    if (!selectedMissionId) {
      setError('Выберите командную миссию.')
      return
    }

    setCreating(true)
    try {
      // Sprint 8.x-4-join-gps: GPS обязателен — бэкенд сохраняет страну/город
      // создателя и проверяет «рядом» при вступлении. Без GPS не создаём.
      const coords = await getCoordsOrThrow()
      const created = await createTeamSession(
        selectedMissionId,
        coords.latitude,
        coords.longitude,
        coords.accuracy,
      )
      setSession(created)
      setNotice('Сессия создана. Друзья могут присоединиться по ID сессии.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setCreating(false)
    }
  }

  // Sprint 8.x-4-join-gps: вступить в чужую сессию по её ID. GPS обязателен:
  // до списания entry fee бэкенд проверяет страну и расстояние (409).
  async function handleJoin() {
    setError(null)
    setNotice(null)

    const targetSessionId = joinSessionId.trim()
    if (!targetSessionId) {
      setError('Укажите ID сессии, к которой нужно присоединиться.')
      return
    }

    setJoining(true)
    try {
      const coords = await getCoordsOrThrow()
      const joined = await joinTeamSession(
        targetSessionId,
        coords.latitude,
        coords.longitude,
        coords.accuracy,
      )
      setSession(joined)
      setJoinSessionId('')
      setNotice(
        'Вы вступили в сессию. Когда все отметятся и будут в зоне — старт автоматически.',
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setJoining(false)
    }
  }

  async function handleReady() {
    if (!session || session.status !== 'collecting') return

    setError(null)
    setNotice(null)
    setReadyBusy(true)
    try {
      const updated = await markTeamSessionReady(session.id)
      setSession(updated)
      setNotice('Вы готовы. Когда все отметятся и будут в зоне — старт автоматически.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setReadyBusy(false)
    }
  }
  // Sprint 8.x-4b-2a: отправка cipher-ответа волны (submitTeamWave).
  async function handleSubmitWave(sequence: string[]) {
    if (!session) return
    setWaveSubmitting(true)
    setWaveError(null)
    setWaveSuccess(null)

    let accepted = false
    try {
      const result = await submitTeamWave(session.id, sequence)
      accepted = result.accepted
      if (!result.accepted) {
        setWaveError(result.message ?? 'Неверная комбинация.')
      } else if (result.sessionStatus === 'succeeded') {
        const rootText =
          result.awarded && result.awarded.root > 0
            ? ` +${result.awarded.root} ROOT`
            : ''
        setWaveSuccess(`Миссия пройдена!${rootText}`)
      } else {
        // Верно, но сыграли не все: волна остаётся 'playing' (ждём
        // остальных — плашка/блокировка в шаге 8.x-4b-2b).
        setWaveSuccess('Верно!')
      }

      // Sprint 8.x-4b-2b: фиксация исхода для финального экрана. /me отдаёт
      // только активные сессии, поэтому succeeded/failed приходит только в
      // ответе submit-wave; на следующем поллинге session станет null — без
      // этого финальный экран не показать.
      if (result.sessionStatus === 'succeeded') {
        setFinalStatus('succeeded')
      } else if (result.sessionStatus === 'failed') {
        setFinalStatus('failed')
        setLastAwarded(null)
      }
      // Sprint 8.x-4-final-status-2: награды сохраняем при ЛЮБОМ верном ответе
      // (не только у последнего отправившего с sessionStatus='succeeded') —
      // «не последний» тоже получил свои награды (в своём ответе submit-wave)
      // и должен увидеть их на финальном экране.
      if (accepted && result.awarded) setLastAwarded(result.awarded)
    } catch (err) {
      setWaveError((err as Error).message)
    } finally {
      setWaveSubmitting(false)
    }

    // После верного ответа — полный объект сессии (свежий myWavePlayed,
    // при финализации cipherSession=null/new). Частичный result из
    // submitTeamWave cipherSession не содержит. При провале волны свежий
    // объект принесёт polling (~3 сек) — чтобы игрок успел увидеть ошибку
    // до пересборки игры, здесь не обновляем.
    if (accepted) {
      try {
        const fresh = await getTeamSessions()
        setSession((current) => fresh.sessions[0] ?? current)
      } catch {
        // тихо: следующее polling обновит состояние.
      }
    }
  }

  // «ЗАНОВО» в командной волне: перезапуск таймера и позиций барабанов.
  function handleResetWave() {
    setWaveError(null)
    setResetSignal((value) => value + 1)
  }

  // Sprint 8.x-4-location-ui: GPS-координаты (паттерн useGameState.ts).
  function getCurrentPosition(): Promise<GeolocationPosition> {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error('Геолокация не поддерживается устройством.'))
        return
      }
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      })
    })
  }

  // Sprint 8.x-4-join-gps: координаты для create/join + человекочитаемая
  // ошибка GPS (как в useGameState.acceptMission). Без координат create/join
  // не выполняются — бэкенд отвечает 422.
  async function getCoordsOrThrow(): Promise<{
    latitude: number
    longitude: number
    accuracy: number | null
  }> {
    let position: GeolocationPosition
    try {
      position = await getCurrentPosition()
    } catch (geoErr) {
      const code =
        geoErr instanceof GeolocationPositionError ? geoErr.code : null
      const message =
        code === 1
          ? 'Отказано в доступе к геолокации. Разрешите доступ и повторите.'
          : code === 2
            ? 'Не удалось определить местоположение. Повторите попытку.'
            : code === 3
              ? 'Таймаут геолокации. Повторите попытку.'
              : (geoErr as Error).message
      throw new Error(message)
    }

    const { latitude, longitude, accuracy } = position.coords
    return {
      latitude,
      longitude,
      // Контракт бэкенда: accuracy > 0 или null (0/NaN не отправляем).
      accuracy: Number.isFinite(accuracy) && accuracy > 0 ? accuracy : null,
    }
  }

  // Отметить гео-присутствие в командной сессии: свежий verified proof нужен
  // для активации после того, как все участники готовы.
  async function handleSubmitLocation() {
    if (!session) return
    if (session.status !== 'ready_to_start') {
      return
    }
    setLocationNotice(null)
    try {
      let coords: GeolocationPosition
      try {
        coords = await getCurrentPosition()
      } catch (geoErr) {
        const code =
          geoErr instanceof GeolocationPositionError ? geoErr.code : null
        const geoMessage =
          code === 1
            ? 'Отказано в доступе к геолокации. Разрешите доступ и повторите.'
            : code === 2
              ? 'Не удалось определить местоположение. Повторите попытку.'
              : code === 3
                ? 'Таймаут геолокации. Повторите попытку.'
                : (geoErr as Error).message
        throw new Error(geoMessage)
      }

      const result = await submitTeamLocation(
        session.id,
        coords.coords.latitude,
        coords.coords.longitude,
        coords.coords.accuracy,
      )
      if (result.verified) {
        setLocationOk(true)
        setLocationNotice('Присутствие подтверждено.')
      } else {
        setLocationOk(false)
        setLocationNotice('Вы вне зоны миссии. Подойдите ближе и попробуйте снова.')
      }

      // Свежее состояние сессии (возможен авто-старт/смена статуса).
      try {
        const fresh = await getTeamSessions()
        setSession((current) => fresh.sessions[0] ?? current)
      } catch {
        // тихо: polling обновит состояние.
      }
    } catch (err) {
      setLocationOk(false)
      setLocationNotice(`Ошибка: ${(err as Error).message}`)
    }
  }

  // Sprint 6.6-b: отправить сообщение в чат сессии.
  async function handleSendMessage() {
    if (!session || sending) return
    const text = messageText.trim()
    if (!text) return

    setSending(true)
    setChatError(null)
    try {
      await sendTeamSessionMessage(session.id, text)
      setMessageText('')
      const result = await getTeamSessionMessages(session.id, 50)
      setMessages(result.messages)
      setMessagesHasMore(result.hasMore)
    } catch {
      setChatError('Не удалось отправить сообщение.')
    } finally {
      setSending(false)
    }
  }

  // Sprint 6.6-b: «Показать ещё» — более старые сообщения (before=createdAt
  // самого старого загруженного, выдача новых сверху).
  async function handleShowMoreMessages() {
    if (!session || messagesBusy || messages.length === 0) return

    const oldest = messages[messages.length - 1]
    setMessagesBusy(true)
    setChatError(null)
    try {
      const result = await getTeamSessionMessages(
        session.id,
        50,
        oldest.createdAt,
      )
      setMessages((prev) => [...prev, ...result.messages])
      setMessagesHasMore(result.hasMore)
    } catch {
      setChatError('Не удалось загрузить историю чата.')
    } finally {
      setMessagesBusy(false)
    }
  }

  return (
    <section className="inventory">
      <p className="eyebrow">КОМАНДНАЯ МИССИЯ / СЕССИЯ</p>
      <h2>Командные сессии</h2>

      {loading && <p>Загрузка…</p>}

      {error && <p className="repair-error">{error}</p>}
      {notice && <p className="mission-success-card">{notice}</p>}

      {/* Sprint 8.x-4b-2b: сессия закончилась, но исход неизвестен (кто-то
          из команды финализировал её, пока мы ждали) — сессия пропала из
          /me. Не оставляем пустоту и не провоцируем создание новой сессии. */}
      {!loading && session === null && finalStatus === null && sessionEnded && (
        <div className="gas-block">
          <h3>Сессия завершена</h3>
          <p>Спасибо за игру! Командная сессия завершена.</p>
          <button
            type="button"
            className="primary-button"
            onClick={() => onScreenChange('terminal')}
          >
            ВЕРНУТЬСЯ В КОНТУР
          </button>
        </div>
      )}

      {!loading && session === null && finalStatus === null && !sessionEnded && (
        <div className="gas-block">
          <h3>Создать сессию</h3>

          <label>
            Миссия
            <select
              value={selectedMissionId}
              disabled={creating}
              onChange={(e) => setSelectedMissionId(e.target.value)}
            >
              <option value="">Выберите командную миссию</option>
              {teamMissionsList.map((mission) => (
                <option key={mission.id} value={mission.id}>
                  {mission.title}
                </option>
              ))}
            </select>
          </label>

          {teamMissionsList.length === 0 && (
            <p className="admin-muted">Командных миссий пока нет.</p>
          )}

          <button
            type="button"
            className="primary-button"
            disabled={creating || teamMissionsList.length === 0}
            onClick={handleCreate}
          >
            {creating ? 'Создаём…' : 'Создать сессию'}
          </button>
        </div>
      )}

      {/* Sprint 8.x-4-join-gps: вступление в чужую сессию по ID. GPS
          запрашивается при нажатии — до списания entry fee бэкенд проверяет
          «одна страна» и «рядом ≤ 50 км до всех участников». */}
      {!loading && session === null && finalStatus === null && !sessionEnded && (
        <div className="gas-block">
          <h3>Вступить в сессию</h3>

          <label>
            ID сессии
            <input
              value={joinSessionId}
              disabled={joining}
              placeholder="team-session-…"
              onChange={(e) => setJoinSessionId(e.target.value)}
            />
          </label>

          <button
            type="button"
            className="primary-button"
            disabled={joining || joinSessionId.trim().length === 0}
            onClick={handleJoin}
          >
            {joining ? 'Вступаем…' : 'Вступить'}
          </button>
        </div>
      )}

      {/* Sprint 8.x-4b-2b: финальные экраны командной мини-игры. Показываем по
          зафиксированному исходу (finalStatus): из ответа submit-wave (свой
          ход) и/или из /last после того, как поллинг потерял сессию.
          Кнопка возврата — в контур (миссии/терминал). */}
      {!loading && finalStatus === 'succeeded' && (
        <div className="mission-success-card">
          <h3>МИССИЯ ПРОЙДЕНА</h3>
          {session?.memberCount != null && session.memberCount > 0 && (
            <p>Вся команда прошла волны.</p>
          )}
          {lastAwarded !== null && (
            <>
              {lastAwarded.root > 0 && (
                <p>Награда: +{lastAwarded.root} ROOT</p>
              )}
              {lastAwarded.items.length > 0 && (
                <p>
                  Предметы:{' '}
                  {lastAwarded.items
                    .map((item) => `${item.title} ×${item.quantity}`)
                    .join(', ')}
                </p>
              )}
              {lastAwarded.storyNodeIds.length > 0 && (
                <p>Открыто сюжетных узлов: {lastAwarded.storyNodeIds.length}</p>
              )}
            </>
          )}
          {/* Sprint 6.6-b: после финала чат закрыт (бэкенд отдаёт 409). */}
          <p className="admin-muted">Чат закрыт.</p>
          <button
            type="button"
            className="primary-button"
            onClick={() => onScreenChange('terminal')}
          >
            ВЕРНУТЬСЯ В КОНТУР
          </button>
        </div>
      )}

      {!loading && finalStatus === 'failed' && (
        <div className="repair-error">
          <h3>МИССИЯ ПРОВАЛЕНА</h3>
          <p>Одна из попыток команды провалена. Волны исчерпаны.</p>
          {/* Sprint 8.x-4-final-status-2: игрок мог честно пройти свои волны,
              пока команда не провалилась — его награды остаются и показываются
              (из снапшота submit-wave / /last). */}
          {lastAwarded !== null && (
            <>
              {lastAwarded.root > 0 && (
                <p>Награда: +{lastAwarded.root} ROOT</p>
              )}
              {lastAwarded.items.length > 0 && (
                <p>
                  Предметы:{' '}
                  {lastAwarded.items
                    .map((item) => `${item.title} ×${item.quantity}`)
                    .join(', ')}
                </p>
              )}
              {lastAwarded.storyNodeIds.length > 0 && (
                <p>Открыто сюжетных узлов: {lastAwarded.storyNodeIds.length}</p>
              )}
            </>
          )}
          {/* Sprint 6.6-b: после финала чат закрыт (бэкенд отдаёт 409). */}
          <p className="admin-muted">Чат закрыт.</p>
          <button
            type="button"
            className="primary-button"
            onClick={() => onScreenChange('terminal')}
          >
            ВЕРНУТЬСЯ В КОНТУР
          </button>
        </div>
      )}

      {!loading && session !== null && (
        <div className="gas-block">
          <h3>{session.missionTitle ?? session.mission_id}</h3>

          <p>
            Статус:{' '}
            <b>{SESSION_STATUS_LABELS[session.status] ?? session.status}</b>
          </p>
          <p>
            Участников: <b>{session.memberCount}</b>
          </p>

          {session.status === 'collecting' && (
            <>
              {session.myStatus === 'joined' && (
                <button
                  type="button"
                  className="primary-button"
                  disabled={readyBusy}
                  onClick={handleReady}
                >
                  {readyBusy ? 'Отправка…' : 'Ready — я готов(а)'}
                </button>
              )}
              {session.myStatus === 'ready' && (
                <p>
                  Вы отметились ({String(!!session.myReadyAt)}). Ждём остальных
                  участников.
                </p>
              )}
            </>
          )}

          {session.status === 'ready_to_start' && (
            <p>
              Все готовы. Как только у всех участников будет свежая отметка
              присутствия в зоне миссии — игра начнётся автоматически.
            </p>
          )}

          {/* Sprint 8.x-4-ux-fix: кнопка «ОТМЕТИТЬ ПРИСУТСТВИЕ» удалена (костыль
              dev-проверки) — гео отправляется автоматически (useEffect выше).
              Сообщения (подтверждено / вне зоны / ошибка) — текстом. */}
          {session.status === 'ready_to_start' &&
            locationNotice && (
              <p
                className={
                  locationOk ? 'mission-success-card' : 'repair-error'
                }
              >
                {locationNotice}
              </p>
            )}

          {session.status === 'active' && (
            <>
              {/* Счётчик — как в solo (cipher-timer), переиспользуем класс. */}
              <div className="cipher-timer">
                ПОПЫТКА {session.currentWave} / {session.maxWaves}
              </div>

              {/* Sprint 8.x-4b-2b: плашка «член команды провалил попытку»
                  (3 сек, гаснет по таймеру в useEffect). */}
              {waveFailedNotice && (
                <p className="repair-error">{waveFailedNotice}</p>
              )}

              {session.myWavePlayed && session.waveStatus === 'playing' ? (
                /* Игрок уже верно сыграл эту волну — ждём остальных. Барабаны
                   и таймер скрыты: повторный сабмит невозможен (409 «уже
                   сыграл»), и auto-submit пустой sequence по таймауту
                   CipherGame не сработает. */
                <p className="admin-muted">
                  {session.wavePlayedCount < session.memberCount
                    ? `Вы сыграли. Ждём других игроков: ${session.wavePlayedCount}/${session.memberCount}.`
                    : 'Вы сыграли. Ждём остальных участников.'}
                </p>
              ) : session.cipherSession ? (
                <CipherGame
                  drums={session.cipherSession.drums}
                  correctCode={session.cipherSession.correctCode}
                  timeLimitSeconds={session.cipherSession.timeLimitSeconds}
                  onSubmit={handleSubmitWave}
                  // Sprint 8.x-4b-2b: myWavePlayed блокирует «ГОТОВО» —
                  // защита от повторного сабмита на случай рассинхрона.
                  isSubmitting={waveSubmitting || session.myWavePlayed}
                  resetSignal={resetSignal}
                  onReset={handleResetWave}
                  // CipherGame сам рендерит ошибку (repair-error) — не дублируем.
                  error={waveError}
                  title="КОМАНДНАЯ МИНИ-ИГРА"
                />
              ) : (
                <p>Игровая сессия завершена.</p>
              )}

              {waveSuccess && !session.myWavePlayed && (
                <p className="mission-success-card">{waveSuccess}</p>
              )}
            </>
          )}

          {/* Sprint 6.6-b: чат команды (только пока сессия активна). Список —
              новые сверху, polling 3 сек; «Показать ещё» грузит историю
              курсором before=createdAt самого старого сообщения. */}
          {chatOpen && (
            <div className="gas-block">
              <h3>ЧАТ КОМАНДЫ</h3>

              {chatError && <p className="repair-error">{chatError}</p>}

              {messages.length === 0 ? (
                <p className="admin-muted">Сообщений пока нет.</p>
              ) : (
                messages.map((message) => (
                  <article className="message-card" key={message.id}>
                    <p>
                      <b>{message.displayName ?? message.playerId}</b>
                      {' · '}
                      {formatChatTime(message.createdAt)}
                    </p>
                    <p>{message.text}</p>
                  </article>
                ))
              )}

              {messagesHasMore && (
                <button
                  type="button"
                  className="primary-button"
                  disabled={messagesBusy}
                  onClick={() => void handleShowMoreMessages()}
                >
                  {messagesBusy ? 'Загрузка…' : 'ПОКАЗАТЬ ЕЩЁ'}
                </button>
              )}

              <label>
                Сообщение
                <input
                  type="text"
                  value={messageText}
                  maxLength={1000}
                  placeholder="Написать команде"
                  onChange={(event) => {
                    setMessageText(event.target.value)
                    setChatError(null)
                  }}
                />
              </label>

              <button
                type="button"
                className="primary-button"
                disabled={sending || messageText.trim().length === 0}
                onClick={() => void handleSendMessage()}
              >
                {sending ? 'Отправка…' : 'ОТПРАВИТЬ'}
              </button>
            </div>
          )}
        </div>
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}