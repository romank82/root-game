import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import './AdminApp.css'
import {
  archiveMinigameProfile,
  createAdminMission,
  createMinigameProfile,
  getAdminMe,
  getMissionRuntimePolicyByMission,
  listAdminMissions,
  listARObjects,
  listGeoZones,
  listKeyItems,
  listMinigameProfiles,
  loginAdmin,
  logoutAdmin,
  publishAdminMission,
  publishMinigameProfile,
  publishMissionRuntimePolicy,
  unpublishAdminMission,
  updateAdminMission,
  updateMinigameProfile,
  upsertMissionRuntimePolicy,
  type AdminARObject,
  type AdminGeoZone,
  type AdminMinigameProfile,
  type AdminMission,
  type AdminMissionPayload,
  type AdminUser,
  type KeyItem,
  type MissionRuntimePolicy,
} from './api/adminApi'

import { SettingsSection } from './components/admin/SettingsSection'
import { AdminsSection } from './components/admin/AdminsSection'
import { KeysSection } from './components/admin/KeysSection'
import { ContentSection } from './components/admin/ContentSection'

type RewardForm = {
  rewardType: string
  amount: string
  itemId: string
  storyNodeId: string
  sortOrder: string
}

type MissionForm = {
  chapterId: string
  storyNodeId: string
  geoZoneId: string
  arObjectId: string
  minigameProfileId: string
  slug: string
  missionType: string
  missionCategory: string
  missionLayer: string
  executionTimeLimitSeconds: string
  reentryCooldownSeconds: string
  unlockAfterMissionId: string
  title: string
  description: string
  content: string
  contentLabel: string
  contentQuestion: string
  contentInputPlaceholder: string
  contentSuccessTitle: string
  contentSuccessText: string
  contentInstruction: string
  contentBlocks: string[]
  contentLineNumber: string
  contentPlaceholder: string
  contentWrongAnswerText: string
  contentDrumCount: string
  contentAlphabet: string[]
  contentFalseChoicesPerDrum: string
  contentCombination: string
  contentTimeLimitSeconds: string
  validationConfig: string
  validationValidator: string
  validationAcceptedAnswers: string[]
  validationCorrectSequence: string[]
  validationCorrectCombination: string[]
  sortOrder: string
  rewards: RewardForm[]
}

const emptyReward = (): RewardForm => ({
  rewardType: 'currency',
  amount: '1',
  itemId: '',
  storyNodeId: '',
  sortOrder: '0',
})

const emptyForm = (): MissionForm => ({
  chapterId: '',
  storyNodeId: '',
  geoZoneId: '',
  arObjectId: '',
  minigameProfileId: '',
  slug: '',
  missionType: 'text_answer',
  missionCategory: 'solo',
  missionLayer: 'solo',
  executionTimeLimitSeconds: '',
  reentryCooldownSeconds: '0',
  unlockAfterMissionId: '',
  title: '',
  description: '',
  content: '{}',
  contentLabel: '',
  contentQuestion: '',
  contentInputPlaceholder: '',
  contentSuccessTitle: '',
  contentSuccessText: '',
  contentInstruction: '',
  contentBlocks: [''],
  contentLineNumber: '',
  contentPlaceholder: '',
  contentWrongAnswerText: '',
  contentDrumCount: '4',
  contentAlphabet: ['R', 'O', 'T', 'G', 'A', 'M', 'E'],
  contentFalseChoicesPerDrum: '2',
  contentCombination: '',
  contentTimeLimitSeconds: '',
  validationConfig:
    '{"validator":"normalized_text_match","acceptedAnswers":[]}',
  validationValidator: 'normalized_text_match',
  validationAcceptedAnswers: [''],
  validationCorrectSequence: [''],
  validationCorrectCombination: [''],
  sortOrder: '0',
  rewards: [emptyReward()],
})

function prettyJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}

function formFromMission(mission: AdminMission): MissionForm {
  const isTextAnswer = mission.missionType === 'text_answer'
  const isCodeRepair = mission.missionType === 'code_repair'
  const isCipher = mission.missionType === 'cipher'
  const hasContentObject =
    (isTextAnswer || isCodeRepair || isCipher) &&
    mission.content !== null &&
    typeof mission.content === 'object'
  const ui =
    hasContentObject &&
    typeof (mission.content as Record<string, unknown>).ui === 'object' &&
    (mission.content as Record<string, unknown>).ui !== null
      ? ((mission.content as Record<string, unknown>).ui as Record<
          string,
          unknown
        >)
      : {}
  const uiEntry = (key: string): string => {
    const value = ui[key]
    return typeof value === 'string' ? value : ''
  }

  const blocksRaw = isCodeRepair && Array.isArray(ui.blocks) ? ui.blocks : []
  const cleanBlocks = blocksRaw.filter(
    (b): b is string => typeof b === 'string' && b.trim().length > 0,
  )

  const cipherAlphabetRaw =
    isCipher && Array.isArray(ui.alphabet) ? ui.alphabet : []
  const cleanCipherAlphabet = cipherAlphabetRaw.filter(
    (a): a is string => typeof a === 'string' && a.trim().length > 0,
  )
  const cipherAlphabetFallback = ['R', 'O', 'T', 'G', 'A', 'M', 'E']

  const isStructuredValidation =
    mission.missionType === 'text_answer' ||
    mission.missionType === 'code_repair' ||
    mission.missionType === 'cipher'

  let validationConfig: string
  let validationValidator: string
  let validationAcceptedAnswers: string[]
  let validationCorrectSequence: string[]
  let validationCorrectCombination: string[]

  if (isStructuredValidation) {
    const cfg =
      mission.validationConfig !== null &&
      typeof mission.validationConfig === 'object'
        ? (mission.validationConfig as Record<string, unknown>)
        : {}

    validationValidator =
      typeof cfg.validator === 'string'
        ? cfg.validator
        : mission.missionType === 'code_repair'
          ? 'ordered_blocks_match'
          : mission.missionType === 'cipher'
            ? 'cipher_match'
            : 'normalized_text_match'

    const acceptedRaw = Array.isArray(cfg.acceptedAnswers)
      ? cfg.acceptedAnswers
      : []
    const accepted = acceptedRaw.filter(
      (a): a is string => typeof a === 'string' && a.trim().length > 0,
    )
    validationAcceptedAnswers = accepted.length > 0 ? accepted : ['']

    const sequenceRaw = Array.isArray(cfg.correctSequence)
      ? cfg.correctSequence
      : []
    const sequence = sequenceRaw.filter(
      (s): s is string => typeof s === 'string' && s.trim().length > 0,
    )
    validationCorrectSequence = sequence.length > 0 ? sequence : ['']

    if (isCipher && cfg.validator === 'cipher_match') {
      const combinationRaw = Array.isArray(cfg.correctCombination)
        ? cfg.correctCombination
        : []
      const combination = combinationRaw.filter(
        (c): c is string => typeof c === 'string' && c.trim().length > 0,
      )
      validationCorrectCombination =
        combination.length > 0 ? combination : ['']
    } else {
      validationCorrectCombination = ['']
    }

    validationConfig = ''
  } else {
    validationConfig = prettyJson(mission.validationConfig)
    validationValidator = 'normalized_text_match'
    validationAcceptedAnswers = ['']
    validationCorrectSequence = ['']
    validationCorrectCombination = ['']
  }

  return {
    chapterId: mission.chapterId,
    storyNodeId: mission.storyNodeId ?? '',
    geoZoneId: mission.geoZoneId ?? '',
    arObjectId: mission.arObjectId ?? '',
    minigameProfileId: mission.minigameProfileId ?? '',
    slug: mission.slug,
    missionType: mission.missionType,
    missionCategory: mission.missionCategory ?? 'solo',
    missionLayer: mission.missionLayer ?? 'solo',
    executionTimeLimitSeconds:
      mission.executionTimeLimitSeconds === null ||
      mission.executionTimeLimitSeconds === undefined
        ? ''
        : String(mission.executionTimeLimitSeconds),
    reentryCooldownSeconds: String(mission.reentryCooldownSeconds ?? 0),
    unlockAfterMissionId: mission.unlockAfterMissionId ?? '',
    title: mission.title,
    description: mission.description ?? '',
    content:
      isTextAnswer || isCodeRepair || isCipher ? '{}' : prettyJson(mission.content),
    contentLabel: uiEntry('label'),
    contentQuestion: uiEntry('question'),
    contentInputPlaceholder: uiEntry('inputPlaceholder'),
    contentSuccessTitle: uiEntry('successTitle'),
    contentSuccessText: uiEntry('successText'),
    contentInstruction:
      isCodeRepair || isCipher ? uiEntry('instruction') : '',
    contentBlocks:
      isCodeRepair && cleanBlocks.length > 0 ? cleanBlocks : [''],
    contentLineNumber: isCodeRepair ? uiEntry('lineNumber') : '',
    contentPlaceholder: isCodeRepair ? uiEntry('placeholder') : '',
    contentWrongAnswerText:
      isCodeRepair || isCipher ? uiEntry('wrongAnswerText') : '',
    contentDrumCount:
      isCipher && ui.drumCount !== undefined ? String(ui.drumCount) : '4',
    contentAlphabet: isCipher ? cleanCipherAlphabet : cipherAlphabetFallback,
    contentFalseChoicesPerDrum:
      isCipher && ui.falseChoicesPerDrum !== undefined
        ? String(ui.falseChoicesPerDrum)
        : '2',
    contentCombination: isCipher ? uiEntry('combination') : '',
    contentTimeLimitSeconds:
      isCipher &&
      ui.timeLimitSeconds !== undefined &&
      ui.timeLimitSeconds !== null
        ? String(ui.timeLimitSeconds)
        : '',
    validationConfig,
    validationValidator,
    validationAcceptedAnswers,
    validationCorrectSequence,
    validationCorrectCombination,
    sortOrder: String(mission.sortOrder),
    rewards: mission.rewards.map((reward) => ({
      rewardType: reward.rewardType,
      amount: reward.amount === null ? '' : String(reward.amount),
      itemId: reward.itemId ?? '',
      storyNodeId: reward.storyNodeId ?? '',
      sortOrder: String(reward.sortOrder),
    })),
  }
}

function parseObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown

  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error(`${label}: введите корректный JSON.`)
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label}: ожидается JSON-объект.`)
  }

  return parsed as Record<string, unknown>
}

function formToPayload(form: MissionForm): AdminMissionPayload {
  const rewards = form.rewards.map((reward) => ({
    reward_type: reward.rewardType.trim(),
    amount: reward.amount.trim() ? Number(reward.amount) : null,
    item_id: reward.itemId.trim() || null,
    story_node_id: reward.storyNodeId.trim() || null,
    reward_value: reward.rewardType === 'currency' ? { currency: 'ROOT' } : {},
    sort_order: Number(reward.sortOrder || 0),
  }))

  let content: Record<string, unknown>
  if (form.missionType === 'text_answer') {
    content = {
      schemaVersion: 1,
      ui: {
        label: form.contentLabel.trim(),
        question: form.contentQuestion.trim(),
        inputPlaceholder: form.contentInputPlaceholder.trim(),
        successTitle: form.contentSuccessTitle.trim(),
        successText: form.contentSuccessText.trim(),
      },
    }
  } else if (form.missionType === 'code_repair') {
    const cleanBlocks = form.contentBlocks
      .map((b) => b.trim())
      .filter((b) => b.length > 0)
    content = {
      schemaVersion: 1,
      ui: {
        label: form.contentLabel.trim(),
        instruction: form.contentInstruction.trim(),
        blocks: cleanBlocks,
        maxBlocks: cleanBlocks.length,
        lineNumber: form.contentLineNumber.trim(),
        placeholder: form.contentPlaceholder.trim(),
        wrongAnswerText: form.contentWrongAnswerText.trim(),
      },
    }
  } else if (form.missionType === 'cipher') {
    const cleanAlphabet = form.contentAlphabet
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    content = {
      schemaVersion: 1,
      ui: {
        label: form.contentLabel.trim(),
        instruction: form.contentInstruction.trim(),
        // 8.17.18: для cipher настройки (drumCount/alphabet/falseChoicesPerDrum/
        // combination/timeLimitSeconds) в content.ui НЕ отправляются — они живут
        // в профиле мини-игры. Код сборки сохранён за условием (см. 8.17.16).
        ...(form.missionType !== 'cipher'
          ? {
              drumCount: Number(form.contentDrumCount),
              alphabet: cleanAlphabet,
              falseChoicesPerDrum: Number(form.contentFalseChoicesPerDrum),
              combination: form.contentCombination.trim(),
              timeLimitSeconds: form.contentTimeLimitSeconds.trim()
                ? Number(form.contentTimeLimitSeconds)
                : null,
            }
          : {}),
        successTitle: form.contentSuccessTitle.trim(),
        successText: form.contentSuccessText.trim(),
        wrongAnswerText: form.contentWrongAnswerText.trim(),
      },
    }
  } else {
    content = parseObject(form.content, 'Content')
  }

  const isStructuredValidation =
    form.missionType === 'text_answer' ||
    form.missionType === 'code_repair' ||
    form.missionType === 'cipher'

  let validation_config: Record<string, unknown>
  if (isStructuredValidation) {
    if (form.validationValidator === 'ordered_blocks_match') {
      validation_config = {
        validator: 'ordered_blocks_match',
        correctSequence: form.validationCorrectSequence
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
      }
    } else if (form.validationValidator === 'cipher_match') {
      validation_config = {
        validator: 'cipher_match',
        // 8.17.18: для cipher correctCombination в validation_config НЕ
        // отправляется (правильный код генерируется на backend). Код сборки
        // сохранён за условием (см. 8.17.16).
        ...(form.missionType !== 'cipher'
          ? {
              correctCombination: form.validationCorrectCombination
                .map((s) => s.trim())
                .filter((s) => s.length > 0),
            }
          : {}),
      }
    } else {
      validation_config = {
        validator: 'normalized_text_match',
        acceptedAnswers: form.validationAcceptedAnswers
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
      }
    }
  } else {
    validation_config = parseObject(form.validationConfig, 'Validation config')
  }

  return {
    chapter_id: form.chapterId.trim(),
    story_node_id: form.storyNodeId.trim() || null,
    geo_zone_id: form.geoZoneId.trim() || null,
    ar_object_id: form.arObjectId.trim() || null,
    minigame_profile_id: form.minigameProfileId.trim() || null,
    slug: form.slug.trim(),
    mission_type: form.missionType.trim(),
    mission_category: form.missionCategory,
    mission_layer: form.missionLayer,
    execution_time_limit_seconds: (() => {
      const raw = form.executionTimeLimitSeconds.trim()
      if (raw === '') return null
      const n = Number.parseInt(raw, 10)
      if (!Number.isFinite(n) || n < 0) return null
      return n
    })(),
    reentry_cooldown_seconds: (() => {
      const raw = form.reentryCooldownSeconds.trim()
      if (raw === '') return 0
      const n = Number.parseInt(raw, 10)
      if (!Number.isFinite(n) || n < 0) return 0
      return n
    })(),
    unlock_after_mission_id: form.unlockAfterMissionId.trim() || null,
    title: form.title.trim(),
    description: form.description.trim() || null,
    content,
    validation_config,
    sort_order: Number(form.sortOrder || 0),
    rewards,
  }
}

function AdminApp() {
  const [admin, setAdmin] = useState<AdminUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMissions, setLoadingMissions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [missions, setMissions] = useState<AdminMission[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState<MissionForm>(emptyForm)
  const [section, setSection] = useState<
    'missions'
    | 'settings'
    | 'admins'
    | 'keys'
    | 'content'
    | 'minigame-profiles'
  >(
    () =>
      (localStorage.getItem('chimera-admin-section') as
        | 'missions'
        | 'settings'
        | 'admins'
        | 'keys'
        | 'content'
        | 'minigame-profiles') ?? 'missions',
  )
  const [geoZones, setGeoZones] = useState<AdminGeoZone[]>([])
  // setGeoZonesError и setARObjectsError всё ещё используются эффектом загрузки миссий;
  // сами geoZonesError/arObjectsError больше не отображаются в AdminApp (редакторы
  // геозон и AR-объектов показывают ошибки сами).
  const [, setGeoZonesError] = useState<string | null>(null)
  const [, setARObjectsError] = useState<string | null>(null)
  const [arObjects, setARObjects] = useState<AdminARObject[]>([])
  const [keyItems, setKeyItems] = useState<KeyItem[]>([])
  const [loadingKeyItems, setLoadingKeyItems] = useState(false)
  const [missionPolicy, setMissionPolicy] = useState<MissionRuntimePolicy | null>(null)
  const [loadingMissionPolicy, setLoadingMissionPolicy] = useState(false)
  const [policyFee, setPolicyFee] = useState('0')
  const [policyItems, setPolicyItems] = useState<Array<{ itemId: string; quantity: string }>>([])
  const [savingPolicy, setSavingPolicy] = useState(false)
  const [policyError, setPolicyError] = useState<string | null>(null)
  const [policyNotice, setPolicyNotice] = useState<string | null>(null)
  const [publishingPolicy, setPublishingPolicy] = useState(false)
  // Minigame profiles (Sprint 8.17)
  const [minigameProfiles, setMinigameProfiles] = useState<
    AdminMinigameProfile[]
  >([])
  const [loadingMinigameProfiles, setLoadingMinigameProfiles] = useState(false)
  const [minigameProfilesError, setMinigameProfilesError] = useState<
    string | null
  >(null)
  const [selectedMinigameProfileId, setSelectedMinigameProfileId] = useState<
    string | null
  >(null)
  const [showCreateMinigameProfile, setShowCreateMinigameProfile] =
    useState(false)
  const [minigameProfileName, setMinigameProfileName] = useState('')
  const [minigameProfileGameType, setMinigameProfileGameType] = useState(
    'cipher',
  )
  // Для cipher:
  const [mgDrumCount, setMgDrumCount] = useState('4')
  const [mgFalseChoices, setMgFalseChoices] = useState('2')
  const [mgTimeLimit, setMgTimeLimit] = useState('60')

  // Для code_repair (пока заглушка):
  const [mgMaxBlocks, setMgMaxBlocks] = useState('3')
  const [savingMinigameProfile, setSavingMinigameProfile] = useState(false)
  const [minigameProfileError, setMinigameProfileError] = useState<
    string | null
  >(null)
  const [minigameProfileNotice, setMinigameProfileNotice] = useState<
    string | null
  >(null)

  useEffect(() => {
    localStorage.setItem('chimera-admin-section', section)
  }, [section])

  useEffect(() => {
    if (section !== 'minigame-profiles') return
    let cancelled = false
    setLoadingMinigameProfiles(true)
    setMinigameProfilesError(null)
    listMinigameProfiles()
      .then((data) => {
        if (cancelled) return
        setMinigameProfiles(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMinigameProfilesError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingMinigameProfiles(false)
      })
    return () => {
      cancelled = true
    }
  }, [section])
  useEffect(() => {
    if (section !== 'missions') return
    let cancelled = false

    listGeoZones()
      .then((data) => {
        if (cancelled) return
        setGeoZones(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setGeoZonesError(err.message)
      })

    listARObjects()
      .then((data) => {
        if (cancelled) return
        setARObjects(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setARObjectsError(err.message)
      })

    listMinigameProfiles()
      .then((data) => {
        if (cancelled) return
        setMinigameProfiles(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMinigameProfilesError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [section])


  useEffect(() => {
    setShowCreateMinigameProfile(false)
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }, [section])

  useEffect(() => {
    if (!selectedMinigameProfileId) {
      setMinigameProfileName('')
      setMinigameProfileGameType('cipher')
      setMgDrumCount('4')
      setMgFalseChoices('2')
      setMgTimeLimit('60')
      setMgMaxBlocks('3')
      setMinigameProfileError(null)
      setMinigameProfileNotice(null)
      return
    }
    const p = minigameProfiles.find((x) => x.id === selectedMinigameProfileId)
    if (!p) return
    setMinigameProfileName(p.name)
    setMinigameProfileGameType(p.gameType)
    const s = p.settings || {}
    if (p.gameType === 'cipher') {
      setMgDrumCount(String(s.drumCount ?? '4'))
      setMgFalseChoices(String(s.falseChoicesPerDrum ?? '2'))
      setMgTimeLimit(
        s.timeLimitSeconds != null ? String(s.timeLimitSeconds) : '',
      )
    } else if (p.gameType === 'code_repair') {
      setMgMaxBlocks(String(s.maxBlocks ?? '3'))
    }
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }, [selectedMinigameProfileId, minigameProfiles])

  const selectedMission = useMemo(
    () => missions.find((mission) => mission.id === selectedId) ?? null,
    [missions, selectedId],
  )

  const canWrite =
    admin?.isSuperAdmin === true ||
    admin?.role === 'owner' ||
    admin?.role === 'editor'

  async function refreshMissions() {
    setLoadingMissions(true)

    try {
      const nextMissions = await listAdminMissions()
      setMissions(nextMissions)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось загрузить миссии.',
      )
    } finally {
      setLoadingMissions(false)
    }
  }

  useEffect(() => {
    getAdminMe()
      .then(async (currentAdmin) => {
        setAdmin(currentAdmin)
        await refreshMissions()
      })
      .catch((err: unknown) => {
        // 8.18: не глотаем молча — сбой сети выглядел как разлогин.
        console.error('[AdminApp] getAdminMe failed', err)
        setAdmin(null)
        setError(
          err instanceof Error ? err.message : 'Не удалось загрузить сессию админа.',
        )
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoadingKeyItems(true)
    listKeyItems('published')
      .then((data) => {
        if (!cancelled) setKeyItems(data)
      })
      .catch((err: unknown) => {
        // 8.18: не глотаем молча — админ видел пустой dropdown и думал «ключей нет».
        console.error('[AdminApp] listKeyItems failed', err)
        setError(
          err instanceof Error
            ? err.message
            : 'Не удалось загрузить каталог ключей.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoadingKeyItems(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedId === null) {
      setMissionPolicy(null)
      setPolicyFee('0')
      setPolicyItems([])
      setPolicyError(null)
      setPolicyNotice(null)
      return
    }
    let cancelled = false
    setLoadingMissionPolicy(true)
    getMissionRuntimePolicyByMission(selectedId)
      .then((p) => {
        if (!cancelled) {
          setMissionPolicy(p)
          if (p) {
            setPolicyFee(String(p.entryRootAtomic))
            const items = ((p.requiredItemsJson as { items?: Array<{ itemId: string; quantity: number }> }).items ?? [])
            setPolicyItems(items.map((it) => ({ itemId: it.itemId, quantity: String(it.quantity) })))
          } else {
            setPolicyFee('0')
            setPolicyItems([])
          }
          setPolicyError(null)
          setPolicyNotice(null)
        }
      })
      .catch((err: unknown) => {
        // 8.18: критично — ошибка политики неотличима от «политики нет»
        // → риск перезаписать существующую политику (вход/ключи/множители).
        console.error('[AdminApp] getMissionRuntimePolicyByMission failed', err)
        if (!cancelled) {
          setMissionPolicy(null)
          setPolicyError(
            err instanceof Error
              ? err.message
              : 'Не удалось загрузить политику миссии.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingMissionPolicy(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])



  function buildSettingsFromForm(): Record<string, unknown> {
    switch (minigameProfileGameType) {
      case 'cipher': {
        return {
          drumCount: Number(mgDrumCount),
          falseChoicesPerDrum: Number(mgFalseChoices),
          timeLimitSeconds: mgTimeLimit.trim() ? Number(mgTimeLimit) : null,
        }
      }
      case 'code_repair': {
        return { maxBlocks: Number(mgMaxBlocks) }
      }
      case 'text_answer': {
        return {}
      }
      default:
        return {}
    }
  }

  function handleShowCreateMinigameProfile() {
    setShowCreateMinigameProfile(true)
    setSelectedMinigameProfileId(null)
    setMinigameProfileName('')
    setMinigameProfileGameType('cipher')
    setMgDrumCount('4')
    setMgFalseChoices('2')
    setMgTimeLimit('60')
    setMgMaxBlocks('3')
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }

  async function handleCreateMinigameProfile() {
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const settings = buildSettingsFromForm()
      const created = await createMinigameProfile({
        name: minigameProfileName,
        game_type: minigameProfileGameType,
        settings,
      })
      setMinigameProfiles((prev) => [...prev, created])
      setSelectedMinigameProfileId(created.id)
      setShowCreateMinigameProfile(false)
      setMinigameProfileNotice('Создано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handleSaveMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const settings = buildSettingsFromForm()
      const updated = await updateMinigameProfile(selectedMinigameProfileId, {
        name: minigameProfileName,
        game_type: minigameProfileGameType,
        settings,
      })
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Сохранено.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handlePublishMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const updated = await publishMinigameProfile(selectedMinigameProfileId)
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Опубликовано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handleArchiveMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const updated = await archiveMinigameProfile(selectedMinigameProfileId)
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Архивировано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }





  async function handleSavePolicy() {
    if (selectedId === null) return
    const fee = Number.parseInt(policyFee, 10)
    if (!Number.isFinite(fee) || fee < 0) {
      setPolicyError('Цена входа должна быть неотрицательным целым.')
      return
    }
    const items: Array<{ itemId: string; quantity: number }> = []
    const seen = new Set<string>()
    for (const raw of policyItems) {
      if (!raw.itemId) continue
      if (seen.has(raw.itemId)) {
        setPolicyError('Ключи не должны повторяться.')
        return
      }
      const q = Number.parseInt(raw.quantity, 10)
      if (!Number.isFinite(q) || q < 1) {
        setPolicyError('Количество ключа — целое число ≥ 1.')
        return
      }
      seen.add(raw.itemId)
      items.push({ itemId: raw.itemId, quantity: q })
    }
    setSavingPolicy(true)
    setPolicyError(null)
    setPolicyNotice(null)
    try {
      const saved = await upsertMissionRuntimePolicy(selectedId, {
        entry_root_atomic: fee,
        required_items_json: { schemaVersion: 1, items },
      })
      setMissionPolicy(saved)
      setPolicyNotice('Сохранено.')
    } catch (err) {
      setPolicyError((err as Error).message)
    } finally {
      setSavingPolicy(false)
    }
  }

  async function handlePublishPolicy() {
    if (missionPolicy === null) return
    setPublishingPolicy(true)
    setPolicyError(null)
    setPolicyNotice(null)
    try {
      const published = await publishMissionRuntimePolicy(missionPolicy.id)
      setMissionPolicy(published)
      setPolicyNotice('Опубликовано. Правила входа активны для игроков.')
    } catch (err) {
      setPolicyError((err as Error).message)
    } finally {
      setPublishingPolicy(false)
    }
  }

  function selectMission(mission: AdminMission) {
    setSelectedId(mission.id)
    setForm(formFromMission(mission))
    setError('')
    setNotice('')
  }

  function startNewMission() {
    setSelectedId(null)
    setForm(emptyForm())
    setError('')
    setNotice('')
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      await loginAdmin(username, password)
      setPassword('')
      const currentAdmin = await getAdminMe()
      setAdmin(currentAdmin)
      await refreshMissions()
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось выполнить вход.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleLogout() {
    setError('')

    try {
      await logoutAdmin()
    } catch {
      // Cookie might already be absent; local UI state still must be cleared.
    }

    setAdmin(null)
    setMissions([])
    setSelectedId(null)
    setForm(emptyForm())
    setNotice('')
  }

  function changeReward(
    index: number,
    field: keyof RewardForm,
    value: string,
  ) {
    setForm((current) => ({
      ...current,
      rewards: current.rewards.map((reward, rewardIndex) =>
        rewardIndex === index ? { ...reward, [field]: value } : reward,
      ),
    }))
  }

  function addReward() {
    setForm((current) => ({
      ...current,
      rewards: [...current.rewards, emptyReward()],
    }))
  }

  function removeReward(index: number) {
    setForm((current) => ({
      ...current,
      rewards: current.rewards.filter(
        (_, rewardIndex) => rewardIndex !== index,
      ),
    }))
  }

  function changeAcceptedAnswer(index: number, value: string) {
    setForm((current) => ({
      ...current,
      validationAcceptedAnswers: current.validationAcceptedAnswers.map((a, i) =>
        i === index ? value : a,
      ),
    }))
  }

  function addAcceptedAnswer() {
    setForm((current) => ({
      ...current,
      validationAcceptedAnswers: [...current.validationAcceptedAnswers, ''],
    }))
  }

  function removeAcceptedAnswer(index: number) {
    setForm((current) => ({
      ...current,
      validationAcceptedAnswers: current.validationAcceptedAnswers.filter(
        (_, i) => i !== index,
      ),
    }))
  }

  function changeCorrectSequence(index: number, value: string) {
    setForm((current) => ({
      ...current,
      validationCorrectSequence: current.validationCorrectSequence.map((s, i) =>
        i === index ? value : s,
      ),
    }))
  }

  function addCorrectSequence() {
    setForm((current) => ({
      ...current,
      validationCorrectSequence: [...current.validationCorrectSequence, ''],
    }))
  }

  function removeCorrectSequence(index: number) {
    setForm((current) => ({
      ...current,
      validationCorrectSequence: current.validationCorrectSequence.filter(
        (_, i) => i !== index,
      ),
    }))
  }

  function changeContentBlock(index: number, value: string) {
    setForm((current) => ({
      ...current,
      contentBlocks: current.contentBlocks.map((b, i) =>
        i === index ? value : b,
      ),
    }))
  }

  function addContentBlock() {
    setForm((current) => ({
      ...current,
      contentBlocks: [...current.contentBlocks, ''],
    }))
  }

  function removeContentBlock(index: number) {
    setForm((current) => ({
      ...current,
      contentBlocks: current.contentBlocks.filter((_, i) => i !== index),
    }))
  }

  function changeContentAlphabet(index: number, value: string) {
    setForm((current) => ({
      ...current,
      contentAlphabet: current.contentAlphabet.map((a, i) =>
        i === index ? value : a,
      ),
    }))
  }

  function addContentAlphabet() {
    setForm((current) => ({
      ...current,
      contentAlphabet: [...current.contentAlphabet, ''],
    }))
  }

  function removeContentAlphabet(index: number) {
    setForm((current) => ({
      ...current,
      contentAlphabet: current.contentAlphabet.filter((_, i) => i !== index),
    }))
  }

  function changeValidationCorrectCombination(
    index: number,
    value: string,
  ) {
    setForm((current) => ({
      ...current,
      validationCorrectCombination:
        current.validationCorrectCombination.map((c, i) =>
          i === index ? value : c,
        ),
    }))
  }

  function addValidationCorrectCombination() {
    setForm((current) => ({
      ...current,
      validationCorrectCombination: [
        ...current.validationCorrectCombination,
        '',
      ],
    }))
  }

  function removeValidationCorrectCombination(index: number) {
    setForm((current) => ({
      ...current,
      validationCorrectCombination:
        current.validationCorrectCombination.filter((_, i) => i !== index),
    }))
  }

  async function saveMission() {
    setError('')
    setNotice('')
    setSubmitting(true)

    try {
      const payload = formToPayload(form)

      if (!payload.chapter_id || !payload.slug || !payload.title) {
        throw new Error('Заполните chapter ID, slug и название миссии.')
      }

      const mission = selectedMission
        ? await updateAdminMission(selectedMission.id, payload)
        : await createAdminMission(payload)

      setMissions((current) => {
        const exists = current.some((entry) => entry.id === mission.id)
        const next = exists
          ? current.map((entry) => (entry.id === mission.id ? mission : entry))
          : [...current, mission]

        return [...next].sort((first, second) =>
          first.status === second.status
            ? first.sortOrder - second.sortOrder
            : first.status.localeCompare(second.status),
        )
      })

      setSelectedId(mission.id)
      setForm(formFromMission(mission))
      setNotice(
        selectedMission
          ? 'Изменения сохранены.'
          : 'Черновик миссии создан.',
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось сохранить миссию.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function changePublication(action: 'publish' | 'unpublish') {
    if (!selectedMission) {
      return
    }

    setError('')
    setNotice('')
    setSubmitting(true)

    try {
      const mission =
        action === 'publish'
          ? await publishAdminMission(selectedMission.id)
          : await unpublishAdminMission(selectedMission.id)

      setMissions((current) =>
        current.map((entry) => (entry.id === mission.id ? mission : entry)),
      )
      setForm(formFromMission(mission))
      setNotice(
        action === 'publish'
          ? 'Миссия опубликована.'
          : 'Миссия возвращена в черновики.',
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось изменить статус публикации.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <main className="admin-shell">Загрузка admin-панели…</main>
  }

  if (!admin) {
    return (
      <main className="admin-shell admin-login-page">
        <section className="admin-login-card">
          <p className="admin-kicker">CHIMERA PROTOCOL</p>
          <h1>Админ-панель</h1>
          <p className="admin-muted">
            Вход доступен только для авторизованных администраторов.
          </p>

          <form className="admin-login-form" onSubmit={handleLogin}>
            <label>
              Логин
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>

            <label>
              Пароль
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            {error && <p className="admin-error">{error}</p>}

            <button className="admin-primary" disabled={submitting}>
              {submitting ? 'Вход…' : 'Войти'}
            </button>
          </form>

          <a className="admin-back-link" href="/">
            ← Вернуться к игре
          </a>
        </section>
      </main>
    )
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / CONTENT CONTROL</p>
          <h1>
            {section === 'missions' && 'Миссии'}
            {section === 'content' && 'Контент'}
            {section === 'settings' && 'Настройки'}
            {section === 'admins' && 'Администраторы'}
            {section === 'keys' && 'Ключи'}
            {section === 'minigame-profiles' && 'Мини-игры'}
          </h1>

          <nav className="admin-nav">
            <button
              className={section === 'missions' ? 'is-active' : ''}
              onClick={() => setSection('missions')}
            >
              Миссии
            </button>
            <button
              className={section === 'content' ? 'is-active' : ''}
              onClick={() => setSection('content')}
            >
              Контент
            </button>
            <button
              className={section === 'settings' ? 'is-active' : ''}
              onClick={() => setSection('settings')}
            >
              Настройки
            </button>
            {(admin?.isSuperAdmin ?? false) && (
              <button
                className={section === 'admins' ? 'is-active' : ''}
                onClick={() => setSection('admins')}
              >
                Администраторы
              </button>
            )}
            <button
              className={section === 'keys' ? 'is-active' : ''}
              onClick={() => setSection('keys')}
            >
              Ключи
            </button>

            <button
              className={section === 'minigame-profiles' ? 'is-active' : ''}
              onClick={() => setSection('minigame-profiles')}
            >
              Мини-игры
            </button>
          </nav>
        </div>

        <div className="admin-user">
          <span>
            {admin.username} · <b>{admin.role}</b>
          </span>
          <button className="admin-secondary" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </header>

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {section === 'missions' && (
        <div className="admin-layout">
        <aside className="admin-sidebar">
          <button
            className="admin-primary"
            onClick={startNewMission}
            disabled={!canWrite}
          >
            + Новая миссия
          </button>

          <button
            className="admin-refresh"
            onClick={refreshMissions}
            disabled={loadingMissions}
          >
            {loadingMissions ? 'Обновление…' : '↻ Обновить список'}
          </button>

          <div className="admin-mission-list">
            {missions.map((mission) => (
              <button
                className={`admin-mission-row ${
                  selectedId === mission.id ? 'is-active' : ''
                }`}
                key={mission.id}
                onClick={() => selectMission(mission)}
              >
                <span
                  className={`admin-status admin-status-${mission.status}`}
                >
                  {mission.status}
                </span>
                <strong>{mission.title}</strong>
                <small>{mission.slug}</small>
              </button>
            ))}

            {!loadingMissions && missions.length === 0 && (
              <p className="admin-muted">Миссий пока нет.</p>
            )}
          </div>
        </aside>

        <section className="admin-editor">
          <div className="admin-editor-title">
            <div>
              <p className="admin-kicker">
                {selectedMission ? selectedMission.id : 'НОВЫЙ ЧЕРНОВИК'}
              </p>
              <h2>
                {selectedMission ? 'Редактирование миссии' : 'Создание миссии'}
              </h2>
            </div>

            {selectedMission && (
              <span
                className={`admin-status admin-status-${selectedMission.status}`}
              >
                {selectedMission.status}
              </span>
            )}
          </div>

          {!canWrite && (
            <p className="admin-readonly">
              Роль viewer позволяет просматривать миссии, но не изменять их.
            </p>
          )}

          <div className="admin-grid">
            <label>
              Chapter ID *
              <input
                value={form.chapterId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, chapterId: event.target.value })
                }
              />
            </label>

            <label>
              Story node ID
              <input
                value={form.storyNodeId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, storyNodeId: event.target.value })
                }
              />
            </label>

            <label>
              Геозона *
              <select
                value={form.geoZoneId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, geoZoneId: event.target.value })
                }
              >
                <option value="">— не выбрано —</option>
                {form.geoZoneId && !geoZones.some((z) => z.id === form.geoZoneId) && (
                  <option value={form.geoZoneId}>
                    (нет в списке: {form.geoZoneId})
                  </option>
                )}
                {geoZones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.title} · {z.slug} [{z.status}]
                  </option>
                ))}
              </select>
            </label>

            <label>
              AR-объект *
              <select
                value={form.arObjectId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, arObjectId: event.target.value })
                }
              >
                <option value="">— не выбрано —</option>
                {form.arObjectId && !arObjects.some((o) => o.id === form.arObjectId) && (
                  <option value={form.arObjectId}>
                    (нет в списке: {form.arObjectId})
                  </option>
                )}
                {arObjects.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title} · {o.slug} [{o.status}]
                  </option>
                ))}
              </select>
            </label>

            <label>
              Профиль мини-игры *
              <select
                value={form.minigameProfileId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, minigameProfileId: event.target.value })
                }
              >
                <option value="">— не выбрано —</option>
                {form.minigameProfileId &&
                  !minigameProfiles.some(
                    (p) => p.id === form.minigameProfileId,
                  ) && (
                    <option value={form.minigameProfileId}>
                      (нет в списке: {form.minigameProfileId})
                    </option>
                  )}
                {minigameProfiles
                  .filter(
                    (p) =>
                      p.status === 'published' &&
                      p.gameType === form.missionType,
                  )
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.gameType}
                    </option>
                  ))}
              </select>
            </label>

            <label>
              Slug *
              <input
                value={form.slug}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, slug: event.target.value })
                }
              />
            </label>

            <label>
              Формат (как решает игрок)
              <select
                value={form.missionType}
                disabled={!canWrite}
                onChange={(event) => {
                  const nextType = event.target.value
                  // Авто-выбор validator под тип миссии. Админ может
                  // переопределить вручную после, но дефолт согласован с типом.
                  const defaultValidator =
                    nextType === 'code_repair'
                      ? 'ordered_blocks_match'
                      : nextType === 'cipher'
                        ? 'cipher_match'
                        : 'normalized_text_match'
                  setForm({
                    ...form,
                    missionType: nextType,
                    validationValidator: defaultValidator,
                  })
                }}
              >
                <option value="text_answer">
                  text_answer — текстовый ответ
                </option>
                <option value="code_repair">
                  code_repair — восстановить код
                </option>
                <option value="cipher">cipher — кодовый замок</option>
              </select>
            </label>

            <label>
              Категория (кто участвует)
              <select
                value={form.missionCategory}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, missionCategory: event.target.value })
                }
              >
                <option value="solo">solo — один игрок</option>
                <option value="team">team — команда</option>
              </select>
            </label>

            <label>
              Слой (где в интерфейсе)
              <select
                value={form.missionLayer}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, missionLayer: event.target.value })
                }
              >
                <option value="solo">solo — индивидуальные</option>
                <option value="team">team — командные</option>
                <option value="story">story — сюжетные</option>
              </select>
            </label>

            <label className="admin-span-2">
              Название *
              <input
                value={form.title}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
              />
            </label>

            <label className="admin-span-2">
              Описание
              <textarea
                value={form.description}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </label>

            <label>
              Порядок сортировки
              <input
                type="number"
                value={form.sortOrder}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, sortOrder: event.target.value })
                }
              />
            </label>

            <label>
              Время на выполнение
              <select
                value={form.executionTimeLimitSeconds}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, executionTimeLimitSeconds: event.target.value })
                }
              >
                <option value="">— без лимита —</option>
                <option value="300">5 минут</option>
                <option value="900">15 минут</option>
                <option value="3600">1 час</option>
                <option value="21600">6 часов</option>
                <option value="86400">24 часа</option>
                <option value="604800">7 дней</option>
              </select>
            </label>

            <label>
              Повторное взятие
              <select
                value={form.reentryCooldownSeconds}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, reentryCooldownSeconds: event.target.value })
                }
              >
                <option value="0">Одноразовая</option>
                <option value="300">Через 5 минут</option>
                <option value="3600">Через 1 час</option>
                <option value="21600">Через 6 часов</option>
                <option value="86400">Через 24 часа</option>
                <option value="604800">Через 7 дней</option>
              </select>
              <small className="admin-muted">
                «Одноразовая» — после завершения или провала миссия больше не появляется.
              </small>
            </label>

            <label className="admin-span-2">
              Разблокируется после
              <select
                value={form.unlockAfterMissionId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, unlockAfterMissionId: event.target.value })
                }
              >
                <option value="">— без зависимости (доступна сразу) —</option>
                {missions
                  .filter((m) => m.id !== selectedMission?.id)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.title} · {m.slug} [{m.status}]
                    </option>
                  ))}
              </select>
              <small className="admin-muted">
                Миссия станет доступной игроку только после выполнения выбранной.
              </small>
            </label>
          </div>

          {form.missionType === 'text_answer' ? (
            <>
              <label className="admin-span-2">
                Текст на кнопке (label)
                <input
                  value={form.contentLabel}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentLabel: event.target.value })
                  }
                />
              </label>

              <label className="admin-span-2">
                Вопрос
                <textarea
                  value={form.contentQuestion}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentQuestion: event.target.value })
                  }
                />
              </label>

              <label>
                Placeholder поля ввода
                <input
                  value={form.contentInputPlaceholder}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      contentInputPlaceholder: event.target.value,
                    })
                  }
                />
              </label>

              <label>
                Заголовок при успехе
                <input
                  value={form.contentSuccessTitle}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      contentSuccessTitle: event.target.value,
                    })
                  }
                />
              </label>

              <label className="admin-span-2">
                Текст при успехе
                <textarea
                  value={form.contentSuccessText}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      contentSuccessText: event.target.value,
                    })
                  }
                />
              </label>
            </>
          ) : form.missionType === 'code_repair' ? (
            <>
              <label className="admin-span-2">
                Текст на кнопке (label)
                <input
                  value={form.contentLabel}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentLabel: event.target.value })
                  }
                />
              </label>

              <label className="admin-span-2">
                Инструкция
                <textarea
                  value={form.contentInstruction}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentInstruction: event.target.value })
                  }
                />
              </label>

              <div className="admin-validation-list">
                <div className="admin-section-heading">
                  <h4>Блоки кода (публичные)</h4>
                  <button
                    className="admin-secondary"
                    onClick={addContentBlock}
                    disabled={!canWrite}
                  >
                    + Добавить блок
                  </button>
                </div>

                {form.contentBlocks.map((block, index) => (
                  <div className="admin-validation-row" key={index}>
                    <input
                      value={block}
                      disabled={!canWrite}
                      onChange={(event) =>
                        changeContentBlock(index, event.target.value)
                      }
                    />
                    <button
                      className="admin-danger"
                      onClick={() => removeContentBlock(index)}
                      disabled={!canWrite || form.contentBlocks.length <= 1}
                    >
                      Удалить
                    </button>
                  </div>
                ))}
              </div>

              <label>
                Номер строки (lineNumber)
                <input
                  value={form.contentLineNumber}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentLineNumber: event.target.value })
                  }
                />
              </label>

              <label>
                Placeholder окна кода
                <input
                  value={form.contentPlaceholder}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({ ...form, contentPlaceholder: event.target.value })
                  }
                />
              </label>

              <label className="admin-span-2">
                Текст при неверной сборке
                <textarea
                  value={form.contentWrongAnswerText}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      contentWrongAnswerText: event.target.value,
                    })
                  }
                />
              </label>
            </>
          ) : form.missionType === 'cipher' ? (
            <>
              <label className="admin-span-2">
                Заголовок
                <input
                  value={form.contentLabel}
                  disabled={!canWrite}
                  onChange={(e) => setForm({ ...form, contentLabel: e.target.value })}
                />
              </label>

              <label className="admin-span-2">
                Инструкция
                <textarea
                  value={form.contentInstruction}
                  disabled={!canWrite}
                  onChange={(e) => setForm({ ...form, contentInstruction: e.target.value })}
                />
              </label>

              {form.missionType !== 'cipher' && (
                <>
                  <label>
                    Количество барабанов
                    <input
                      type="number"
                      min={2}
                      max={12}
                      value={form.contentDrumCount}
                      disabled={!canWrite}
                      onChange={(e) => setForm({ ...form, contentDrumCount: e.target.value })}
                    />
                  </label>

                  <label>
                    Ложных символов на барабан
                    <input
                      type="number"
                      min={0}
                      max={10}
                      value={form.contentFalseChoicesPerDrum}
                      disabled={!canWrite}
                      onChange={(e) => setForm({ ...form, contentFalseChoicesPerDrum: e.target.value })}
                    />
                  </label>

                  <label className="admin-span-2">
                    Правильная комбинация
                    <input
                      value={form.contentCombination}
                      disabled={!canWrite}
                      placeholder="Например: ROOT"
                      onChange={(e) => setForm({ ...form, contentCombination: e.target.value })}
                    />
                  </label>

                  <label className="admin-span-2">
                    Время на решение (сек, пусто = без лимита)
                    <input
                      type="number"
                      min={1}
                      max={3600}
                      value={form.contentTimeLimitSeconds}
                      disabled={!canWrite}
                      onChange={(e) => setForm({ ...form, contentTimeLimitSeconds: e.target.value })}
                    />
                  </label>
                </>
              )}

              <label className="admin-span-2">
                Заголовок при успехе
                <input
                  value={form.contentSuccessTitle}
                  disabled={!canWrite}
                  onChange={(e) => setForm({ ...form, contentSuccessTitle: e.target.value })}
                />
              </label>

              <label className="admin-span-2">
                Текст при успехе
                <textarea
                  value={form.contentSuccessText}
                  disabled={!canWrite}
                  onChange={(e) => setForm({ ...form, contentSuccessText: e.target.value })}
                />
              </label>

              <label className="admin-span-2">
                Текст при ошибке
                <textarea
                  value={form.contentWrongAnswerText}
                  disabled={!canWrite}
                  onChange={(e) => setForm({ ...form, contentWrongAnswerText: e.target.value })}
                />
              </label>

              {form.missionType !== 'cipher' && (
                <div className="admin-validation-list">
                  <div className="admin-section-heading">
                    <h4>Алфавит символов (публичный)</h4>
                    <button
                      className="admin-secondary"
                      onClick={addContentAlphabet}
                      disabled={!canWrite}
                    >
                      + Добавить символ
                    </button>
                  </div>
                  {form.contentAlphabet.map((symbol, index) => (
                    <div className="admin-validation-row" key={index}>
                      <input
                        value={symbol}
                        disabled={!canWrite}
                        onChange={(e) => changeContentAlphabet(index, e.target.value)}
                      />
                      <button
                        className="admin-danger"
                        onClick={() => removeContentAlphabet(index)}
                        disabled={!canWrite || form.contentAlphabet.length <= 1}
                      >
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <label className="admin-json-field">
              Content (JSON)
              <textarea
                spellCheck={false}
                value={form.content}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, content: event.target.value })
                }
              />
            </label>
          )}

          {form.missionType === 'text_answer' ||
          form.missionType === 'code_repair' ||
          form.missionType === 'cipher' ? (
            <section className="admin-validation-config">
              <div className="admin-section-heading">
                <h3>Правила проверки ответа</h3>
              </div>

              <label>
                Тип проверки
                <select
                  value={form.validationValidator}
                  disabled={!canWrite}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      validationValidator: event.target.value,
                    })
                  }
                >
                  <option value="normalized_text_match">
                    normalized_text_match — сравнить текст ответа
                  </option>
                  <option value="ordered_blocks_match">
                    ordered_blocks_match — собрать правильную последовательность
                  </option>
                  <option value="cipher_match">cipher_match</option>
                </select>
              </label>

              {form.validationValidator === 'normalized_text_match' && (
                <div className="admin-validation-list">
                  <div className="admin-section-heading">
                    <h4>Принятые ответы</h4>
                    <button
                      className="admin-secondary"
                      onClick={addAcceptedAnswer}
                      disabled={!canWrite}
                    >
                      + Добавить ответ
                    </button>
                  </div>

                  {form.validationAcceptedAnswers.map((answer, index) => (
                    <div className="admin-validation-row" key={index}>
                      <input
                        value={answer}
                        disabled={!canWrite}
                        onChange={(event) =>
                          changeAcceptedAnswer(index, event.target.value)
                        }
                      />
                      <button
                        className="admin-danger"
                        onClick={() => removeAcceptedAnswer(index)}
                        disabled={
                          !canWrite ||
                          form.validationAcceptedAnswers.length <= 1
                        }
                      >
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {form.validationValidator === 'ordered_blocks_match' && (
                <div className="admin-validation-list">
                  <div className="admin-section-heading">
                    <h4>Правильная последовательность</h4>
                    <button
                      className="admin-secondary"
                      onClick={addCorrectSequence}
                      disabled={!canWrite}
                    >
                      + Добавить блок
                    </button>
                  </div>

                  {form.validationCorrectSequence.map((block, index) => (
                    <div className="admin-validation-row" key={index}>
                      <input
                        value={block}
                        disabled={!canWrite}
                        onChange={(event) =>
                          changeCorrectSequence(index, event.target.value)
                        }
                      />
                      <button
                        className="admin-danger"
                        onClick={() => removeCorrectSequence(index)}
                        disabled={
                          !canWrite ||
                          form.validationCorrectSequence.length <= 1
                        }
                      >
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {form.missionType !== 'cipher' &&
              form.validationValidator === 'cipher_match' && (
                <div className="admin-validation-list">
                  <div className="admin-section-heading">
                    <h4>Правильная комбинация</h4>
                    <button
                      className="admin-secondary"
                      onClick={addValidationCorrectCombination}
                      disabled={!canWrite}
                    >
                      + Добавить символ
                    </button>
                  </div>
                  {form.validationCorrectCombination.map((symbol, index) => (
                    <div className="admin-validation-row" key={index}>
                      <input
                        value={symbol}
                        disabled={!canWrite}
                        onChange={(e) => changeValidationCorrectCombination(index, e.target.value)}
                      />
                      <button
                        className="admin-danger"
                        onClick={() => removeValidationCorrectCombination(index)}
                        disabled={
                          !canWrite ||
                          form.validationCorrectCombination.length <= 1
                        }
                      >
                        Удалить
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : (
            <label className="admin-json-field">
              Validation config (JSON, закрытые данные)
              <textarea
                spellCheck={false}
                value={form.validationConfig}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, validationConfig: event.target.value })
                }
              />
            </label>
          )}

          <section className="admin-runtime-policy">
            <div className="admin-section-heading">
              <h3>Взятие миссии</h3>
            </div>

            {loadingMissionPolicy && (
              <p className="admin-muted">Загрузка правил…</p>
            )}

            {!loadingMissionPolicy && (
              <>
                {policyError && <p className="admin-alert admin-error">{policyError}</p>}
                {policyNotice && <p className="admin-alert admin-notice">{policyNotice}</p>}

                {missionPolicy !== null && (
                  <p className="admin-muted" style={{ marginBottom: 10 }}>
                    Статус правил: <b>{missionPolicy.status}</b>
                    {missionPolicy.version > 0 && ` · v${missionPolicy.version}`}
                    {missionPolicy.status === 'draft' && ' — не активны для игроков'}
                    {missionPolicy.status === 'published' && ' — активны для игроков'}
                  </p>
                )}

                {missionPolicy !== null && (
                  <p className="admin-muted" style={{ marginBottom: 10 }}>
                    Правила входа уже сохранены для этой миссии.
                  </p>
                )}

                <label className="admin-field">
                  <span>Цена входа (ROOT)</span>
                  <input
                    type="number"
                    min={0}
                    value={policyFee}
                    onChange={(e) => setPolicyFee(e.target.value)}
                    disabled={savingPolicy}
                  />
                </label>

                <label className="admin-field">
                  <span>Требуемые ключи</span>
                </label>

                <div className="admin-required-items-edit">
                  {policyItems.map((row, idx) => (
                    <div className="admin-required-item-row" key={idx}>
                      <select
                        value={row.itemId}
                        onChange={(e) => {
                          const next = [...policyItems]
                          next[idx] = { ...next[idx], itemId: e.target.value }
                          setPolicyItems(next)
                        }}
                        disabled={savingPolicy}
                      >
                        <option value="">— выберите ключ —</option>
                        {keyItems.map((k) => (
                          <option key={k.id} value={k.id}>
                            {k.symbol ? `${k.symbol} ` : ''}{k.title} · {k.code}
                          </option>
                        ))}
                      </select>
                      <input
                        type="number"
                        min={1}
                        value={row.quantity}
                        onChange={(e) => {
                          const next = [...policyItems]
                          next[idx] = { ...next[idx], quantity: e.target.value }
                          setPolicyItems(next)
                        }}
                        disabled={savingPolicy}
                        placeholder="шт"
                      />
                      <button
                        type="button"
                        className="admin-multiplier-remove"
                        onClick={() => setPolicyItems(policyItems.filter((_, i) => i !== idx))}
                        disabled={savingPolicy}
                      >
                        ×
                      </button>
                    </div>
                  ))}

                  <button
                    type="button"
                    className="admin-multiplier-add"
                    onClick={() => setPolicyItems([...policyItems, { itemId: '', quantity: '1' }])}
                    disabled={savingPolicy || keyItems.length === 0}
                  >
                    + Добавить ключ
                  </button>
                </div>

                <div className="admin-actions" style={{ marginTop: 16 }}>
                  <button
                    className="admin-primary"
                    onClick={handleSavePolicy}
                    disabled={savingPolicy}
                  >
                    {savingPolicy ? 'Сохранение…' : 'Сохранить'}
                  </button>

                  {missionPolicy !== null && missionPolicy.status === 'draft' && (
                    <button
                      className="admin-secondary"
                      onClick={handlePublishPolicy}
                      disabled={publishingPolicy || savingPolicy}
                    >
                      {publishingPolicy ? 'Публикация…' : 'Опубликовать'}
                    </button>
                  )}
                </div>
              </>
            )}
          </section>

          <section className="admin-rewards">
            <div className="admin-section-heading">
              <h3>Награды</h3>
              <button
                className="admin-secondary"
                onClick={addReward}
                disabled={!canWrite}
              >
                + Награда
              </button>
            </div>

            {form.rewards.map((reward, index) => (
              <div className="admin-reward-card" key={index}>
                <label>
                  Тип
                  <select
                    value={reward.rewardType}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'rewardType', event.target.value)
                    }
                  >
                    <option value="currency">currency</option>
                    <option value="item">item</option>
                    <option value="story_node">story_node</option>
                  </select>
                </label>

                {reward.rewardType !== 'story_node' && (
                  <label>
                    Amount
                    <input
                      type="number"
                      value={reward.amount}
                      disabled={!canWrite}
                      onChange={(event) =>
                        changeReward(index, 'amount', event.target.value)
                      }
                    />
                  </label>
                )}

                {reward.rewardType === 'item' && (
                  <label>
                    Ключ (item)
                    <select
                      value={reward.itemId}
                      disabled={!canWrite || loadingKeyItems}
                      onChange={(e) =>
                        changeReward(index, 'itemId', e.target.value)
                      }
                    >
                      <option value="">
                        {loadingKeyItems ? 'Загрузка…' : '— не выбрано —'}
                      </option>
                      {reward.itemId &&
                        !keyItems.some((ki) => ki.id === reward.itemId) && (
                          <option value={reward.itemId}>
                            (нет в каталоге: {reward.itemId})
                          </option>
                        )}
                      {keyItems.map((ki) => (
                        <option key={ki.id} value={ki.id}>
                          {ki.symbol ? `${ki.symbol} ` : ''}
                          {ki.title} · {ki.code}
                        </option>
                      ))}
                    </select>
                  </label>
                )}

                {reward.rewardType === 'story_node' && (
                  <label>
                    Story node ID
                    <input
                      value={reward.storyNodeId}
                      disabled={!canWrite}
                      onChange={(event) =>
                        changeReward(index, 'storyNodeId', event.target.value)
                      }
                    />
                  </label>
                )}

                <label>
                  Sort
                  <input
                    type="number"
                    value={reward.sortOrder}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'sortOrder', event.target.value)
                    }
                  />
                </label>

                <button
                  className="admin-danger"
                  onClick={() => removeReward(index)}
                  disabled={!canWrite}
                >
                  Удалить
                </button>
              </div>
            ))}
          </section>

          <div className="admin-actions">
            <button
              className="admin-primary"
              onClick={saveMission}
              disabled={!canWrite || submitting}
            >
              {submitting ? 'Сохранение…' : 'Сохранить'}
            </button>

            {selectedMission?.status === 'draft' && (
              <button
                className="admin-publish"
                onClick={() => changePublication('publish')}
                disabled={!canWrite || submitting}
              >
                Опубликовать
              </button>
            )}

            {selectedMission?.status === 'published' && (
              <button
                className="admin-secondary"
                onClick={() => changePublication('unpublish')}
                disabled={!canWrite || submitting}
              >
                Снять с публикации
              </button>
            )}
          </div>
        </section>
        </div>
      )}

      {section === 'settings' && (
        <SettingsSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {section === 'admins' && (admin?.isSuperAdmin ?? false) && (
        <AdminsSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {section === 'keys' && (
        <KeysSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
          keyItems={keyItems}
        />
      )}

      {section === 'minigame-profiles' && (
        <div className="admin-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-primary"
              onClick={handleShowCreateMinigameProfile}
              disabled={!canWrite}
            >
              + Новый профиль
            </button>
            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedMinigameProfileId(null)
                setMinigameProfiles([])
                setMinigameProfilesError(null)
                setLoadingMinigameProfiles(true)
                listMinigameProfiles()
                  .then(setMinigameProfiles)
                  .catch((err: Error) => setMinigameProfilesError(err.message))
                  .finally(() => setLoadingMinigameProfiles(false))
              }}
              disabled={loadingMinigameProfiles}
            >
              {loadingMinigameProfiles ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {minigameProfilesError && (
              <p className="admin-alert admin-error">{minigameProfilesError}</p>
            )}

            <div className="admin-mission-list">
              {minigameProfiles.map((p) => (
                <button
                  key={p.id}
                  className={`admin-mission-row ${selectedMinigameProfileId === p.id ? 'is-active' : ''}`}
                  onClick={() => {
                    setSelectedMinigameProfileId(p.id)
                    setShowCreateMinigameProfile(false)
                  }}
                >
                  <span className={`admin-status admin-status-${p.status}`}>
                    {p.status}
                  </span>
                  <strong>{p.name}</strong>
                  <small>{p.gameType}</small>
                </button>
              ))}
              {!loadingMinigameProfiles &&
                minigameProfiles.length === 0 &&
                !minigameProfilesError && (
                  <p className="admin-muted">Профилей нет.</p>
                )}
            </div>
          </aside>

          <section className="admin-editor">
            {showCreateMinigameProfile || selectedMinigameProfileId ? (
              <>
                <div className="admin-editor-title">
                  <h2>
                    {showCreateMinigameProfile
                      ? 'Новый профиль мини-игры'
                      : 'Редактирование профиля'}
                  </h2>
                  {selectedMinigameProfileId && (
                    <code>{selectedMinigameProfileId}</code>
                  )}
                  {selectedMinigameProfileId && (
                    <span
                      className={`admin-status admin-status-${
                        minigameProfiles.find(
                          (p) => p.id === selectedMinigameProfileId,
                        )?.status ?? 'draft'
                      }`}
                    >
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status}
                    </span>
                  )}
                </div>

                {minigameProfileError && (
                  <p className="admin-alert admin-error">
                    {minigameProfileError}
                  </p>
                )}
                {minigameProfileNotice && (
                  <p className="admin-alert admin-notice">
                    {minigameProfileNotice}
                  </p>
                )}

                <div className="admin-grid">
                  <label className="admin-span-2">
                    Имя профиля *
                    <input
                      value={minigameProfileName}
                      disabled={!canWrite}
                      onChange={(e) => setMinigameProfileName(e.target.value)}
                    />
                  </label>
                  <label>
                    Тип игры *
                    <select
                      value={minigameProfileGameType}
                      disabled={!canWrite}
                      onChange={(e) => setMinigameProfileGameType(e.target.value)}
                    >
                      <option value="cipher">cipher</option>
                      <option value="code_repair">code_repair</option>
                      <option value="text_answer">text_answer</option>
                    </select>
                  </label>
                  {minigameProfileGameType === 'cipher' && (
                    <>
                      <label>
                        Количество барабанов *
                        <input
                          type="number"
                          min={2}
                          max={12}
                          value={mgDrumCount}
                          disabled={!canWrite}
                          onChange={(e) => setMgDrumCount(e.target.value)}
                        />
                      </label>
                      <label>
                        Ложных символов на барабан *
                        <input
                          type="number"
                          min={0}
                          max={36}
                          value={mgFalseChoices}
                          disabled={!canWrite}
                          onChange={(e) => setMgFalseChoices(e.target.value)}
                        />
                      </label>
                      <label>
                        Время на решение (сек, пусто = без лимита)
                        <input
                          type="number"
                          min={1}
                          max={3600}
                          value={mgTimeLimit}
                          disabled={!canWrite}
                          onChange={(e) => setMgTimeLimit(e.target.value)}
                        />
                      </label>
                    </>
                  )}

                  {minigameProfileGameType === 'code_repair' && (
                    <label>
                      Максимум блоков *
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={mgMaxBlocks}
                        disabled={!canWrite}
                        onChange={(e) => setMgMaxBlocks(e.target.value)}
                      />
                    </label>
                  )}

                  {minigameProfileGameType === 'text_answer' && (
                    <p className="admin-muted">
                      Для этого типа игры параметров пока нет.
                    </p>
                  )}
                </div>

                <div className="admin-actions">
                  {showCreateMinigameProfile ? (
                    <>
                      <button
                        className="admin-primary"
                        onClick={handleCreateMinigameProfile}
                        disabled={!canWrite || savingMinigameProfile}
                      >
                        {savingMinigameProfile ? 'Создание…' : 'Создать'}
                      </button>
                      <button
                        className="admin-secondary"
                        onClick={() => setShowCreateMinigameProfile(false)}
                        disabled={savingMinigameProfile}
                      >
                        Отмена
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="admin-primary"
                        onClick={handleSaveMinigameProfile}
                        disabled={!canWrite || savingMinigameProfile}
                      >
                        {savingMinigameProfile ? 'Сохранение…' : 'Сохранить'}
                      </button>
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status === 'draft' && (
                        <button
                          className="admin-publish"
                          onClick={handlePublishMinigameProfile}
                          disabled={!canWrite || savingMinigameProfile}
                        >
                          Опубликовать
                        </button>
                      )}
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status === 'published' && (
                        <button
                          className="admin-danger"
                          onClick={handleArchiveMinigameProfile}
                          disabled={!canWrite || savingMinigameProfile}
                        >
                          Архивировать
                        </button>
                      )}
                    </>
                  )}
                </div>
              </>
            ) : (
              <p className="admin-muted">Выберите профиль или создайте новый.</p>
            )}
          </section>
        </div>
      )}

      {section === 'content' && (
        <>
          <ContentSection
            admin={admin}
            canWrite={canWrite}
            onError={setError}
            onNotice={setNotice}
            geoZones={geoZones}
            arObjects={arObjects}
            onGeoZonesChange={setGeoZones}
            onARObjectsChange={setARObjects}
          />
        </>
      )}

    </main>
  )
}

export default AdminApp
