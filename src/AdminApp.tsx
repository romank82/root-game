import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import './AdminApp.css'
import {
  archiveMinigameProfile,
  archiveSegment,
  createAdmin,
  createAdminMission,
  createARObject,
  createGeoZone,
  createKeyItem,
  createMinigameProfile,
  createSegment,
  deactivateAdmin,
  getAdminMe,
  getMissionRuntimePolicyByMission,
  grantPermission,
  listAdminMissions,
  listAdmins,
  listARObjects,
  listGeoZones,
  listKeyItems,
  listKeyRules,
  listMinigameProfiles,
  listSegments,
  listSystemSettings,
  loginAdmin,
  logoutAdmin,
  publishAdminMission,
  publishMinigameProfile,
  publishMissionRuntimePolicy,
  publishSegment,
  reactivateAdmin,
  revokePermission,
  unpublishAdminMission,
  unpublishSegment,
  updateAdminMission,
  updateARObject,
  updateGeoZone,
  updateMinigameProfile,
  updateKeyRule,
  updateSegment,
  updateSystemSetting,
  upsertMissionRuntimePolicy,
  PERMISSION_CATALOG,
  type AdminARObject,
  type AdminGeoZone,
  type AdminMinigameProfile,
  type AdminMission,
  type AdminMissionPayload,
  type AdminSegment,
  type AdminSystemSetting,
  type AdminUser,
  type AdminUserFull,
  type KeyItem,
  type KeyRule,
  type MissionRuntimePolicy,
  type PermissionCatalogEntry,
} from './api/adminApi'

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
  const [adminsList, setAdminsList] = useState<AdminUserFull[]>([])
  const [selectedAdminId, setSelectedAdminId] = useState<string | null>(null)
  const [loadingAdmins, setLoadingAdmins] = useState(false)
  const [adminsError, setAdminsError] = useState<string | null>(null)
  const [permReason, setPermReason] = useState<string>('')
  const [permSaving, setPermSaving] = useState<string | null>(null)
  const [permError, setPermError] = useState<string | null>(null)
  const [showCreateAdmin, setShowCreateAdmin] = useState(false)
  const [newAdminUsername, setNewAdminUsername] = useState('')
  const [newAdminPassword, setNewAdminPassword] = useState('')
  const [creatingAdmin, setCreatingAdmin] = useState(false)
  const [createAdminError, setCreateAdminError] = useState<string | null>(null)
  const [deactivateReason, setDeactivateReason] = useState('')
  const [togglingActive, setTogglingActive] = useState(false)
  const [activeError, setActiveError] = useState<string | null>(null)
  const [keyRules, setKeyRules] = useState<KeyRule[]>([])
  const [segments, setSegments] = useState<AdminSegment[]>([])
  const [loadingSegments, setLoadingSegments] = useState(false)
  const [segmentsError, setSegmentsError] = useState<string | null>(null)
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)
  const [contentTab, setContentTab] = useState<'segments' | 'geozones' | 'arobjects'>('segments')

  const [geoZones, setGeoZones] = useState<AdminGeoZone[]>([])
  const [loadingGeoZones, setLoadingGeoZones] = useState(false)
  const [geoZonesError, setGeoZonesError] = useState<string | null>(null)
  const [selectedGeoZoneId, setSelectedGeoZoneId] = useState<string | null>(null)
  const [geoZoneSlug, setGeoZoneSlug] = useState('')
  const [geoZoneTitle, setGeoZoneTitle] = useState('')
  const [geoZoneDescription, setGeoZoneDescription] = useState('')
  const [geoZoneSortOrder, setGeoZoneSortOrder] = useState('0')
  const [geoZoneRadiusMeters, setGeoZoneRadiusMeters] = useState('')
  const [geoZoneSearchRadiusMeters, setGeoZoneSearchRadiusMeters] = useState('')
  const [geoZoneMaxAccuracy, setGeoZoneMaxAccuracy] = useState('')
  const [geoZoneMinPresence, setGeoZoneMinPresence] = useState('0')
  const [geoZoneStatus, setGeoZoneStatus] = useState('draft')
  const [geoZoneAvoidBuildings, setGeoZoneAvoidBuildings] = useState(true)
  const [geoZoneAvoidWater, setGeoZoneAvoidWater] = useState(true)
  const [geoZoneAvoidRoads, setGeoZoneAvoidRoads] = useState(true)
  const [geoZoneAvoidPrivate, setGeoZoneAvoidPrivate] = useState(true)
  const [savingGeoZone, setSavingGeoZone] = useState(false)
  const [geoZoneError, setGeoZoneError] = useState<string | null>(null)
  const [geoZoneNotice, setGeoZoneNotice] = useState<string | null>(null)
  const [showCreateGeoZone, setShowCreateGeoZone] = useState(false)
  const [arObjects, setARObjects] = useState<AdminARObject[]>([])
  const [loadingARObjects, setLoadingARObjects] = useState(false)
  const [arObjectsError, setARObjectsError] = useState<string | null>(null)
  const [selectedARObjectId, setSelectedARObjectId] = useState<string | null>(null)

  const [arObjectSlug, setARObjectSlug] = useState('')
  const [arObjectTitle, setARObjectTitle] = useState('')
  const [arObjectDescription, setARObjectDescription] = useState('')
  const [arObjectGeoZoneId, setARObjectGeoZoneId] = useState('')
  const [arObjectObjectType, setARObjectObjectType] = useState('cube')
  const [arObjectAssetUri, setARObjectAssetUri] = useState('')
  const [arObjectAssetMimeType, setARObjectAssetMimeType] = useState('')
  const [arObjectScenePreset, setARObjectScenePreset] = useState('')
  const [arObjectInstructionText, setARObjectInstructionText] = useState('')
  const [arObjectScaleMeters, setARObjectScaleMeters] = useState('1.0')
  const [arObjectOrientation, setARObjectOrientation] = useState('free')
  const [arObjectSortOrder, setARObjectSortOrder] = useState('0')
  const [arObjectStatus, setARObjectStatus] = useState('draft')
  const [savingARObject, setSavingARObject] = useState(false)
  const [arObjectError, setARObjectError] = useState<string | null>(null)
  const [arObjectNotice, setARObjectNotice] = useState<string | null>(null)
  const [showCreateARObject, setShowCreateARObject] = useState(false)
  const [segmentTitle, setSegmentTitle] = useState('')
  const [segmentSlug, setSegmentSlug] = useState('')
  const [segmentDescription, setSegmentDescription] = useState('')
  const [segmentChapterId, setSegmentChapterId] = useState('')
  const [segmentSortOrder, setSegmentSortOrder] = useState('0')
  const [segmentContentJson, setSegmentContentJson] = useState('{}')
  const [segmentMissions, setSegmentMissions] = useState<
    Array<{ missionId: string; sortOrder: string }>
  >([])
  const [savingSegment, setSavingSegment] = useState(false)
  const [segmentError, setSegmentError] = useState<string | null>(null)
  const [segmentNotice, setSegmentNotice] = useState<string | null>(null)
  const [publishingSegment, setPublishingSegment] = useState(false)
  const [showCreateSegment, setShowCreateSegment] = useState(false)

  const [missionsForLink, setMissionsForLink] = useState<
    Array<{ id: string; slug: string; title: string; chapterId: string; status: string }>
  >([])
  const [loadingMissionsForLink, setLoadingMissionsForLink] = useState(false)
  const [missionsForLinkError, setMissionsForLinkError] = useState<string | null>(null)
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
  const [selectedKeyRuleId, setSelectedKeyRuleId] = useState<string | null>(null)
  const [loadingKeyRules, setLoadingKeyRules] = useState(false)
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
  const [keyRulesError, setKeyRulesError] = useState<string | null>(null)
  const [showCreateKey, setShowCreateKey] = useState(false)
  const [newKeyTitle, setNewKeyTitle] = useState('')
  const [newKeyCode, setNewKeyCode] = useState('')
  const [newKeySymbol, setNewKeySymbol] = useState('')
  const [newKeyConsumable, setNewKeyConsumable] = useState(true)
  const [newKeyStackLimit, setNewKeyStackLimit] = useState('1')
  const [creatingKey, setCreatingKey] = useState(false)
  const [createKeyError, setCreateKeyError] = useState<string | null>(null)
  const [keyEditConsumable, setKeyEditConsumable] = useState(false)
  const [keyEditStackLimit, setKeyEditStackLimit] = useState('1')
  const [keyEditSortOrder, setKeyEditSortOrder] = useState('0')
  const [keyEditTransferForbidden, setKeyEditTransferForbidden] = useState(true)
  const [keyEditSaleForbidden, setKeyEditSaleForbidden] = useState(true)
  const [keyEditTradeForbidden, setKeyEditTradeForbidden] = useState(true)
  const [savingKey, setSavingKey] = useState(false)
  const [savingKeyError, setSavingKeyError] = useState<string | null>(null)
  const [savingKeyNotice, setSavingKeyNotice] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem('chimera-admin-section', section)
  }, [section])

  useEffect(() => {
    if (section !== 'settings') return
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
  }, [section])

  useEffect(() => {
    if (section !== 'settings') return
    if (selectedSettingKey !== null) return
    if (settings.length === 0) return
    setSelectedSettingKey(settings[0].key)
  }, [section, settings, selectedSettingKey])

  useEffect(() => {
    if (section !== 'admins') return
    if (!(admin?.isSuperAdmin ?? false)) return
    let cancelled = false
    setLoadingAdmins(true)
    setAdminsError(null)
    listAdmins()
      .then((data) => {
        if (cancelled) return
        setAdminsList(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setAdminsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingAdmins(false)
      })
    return () => {
      cancelled = true
    }
  }, [section, admin])

  useEffect(() => {
    setPermReason('')
    setPermError(null)
    setPermSaving(null)
    setShowCreateAdmin(false)
    setCreateAdminError(null)
    setDeactivateReason('')
    setActiveError('')
  }, [selectedAdminId])

  useEffect(() => {
    if (section !== 'keys') return
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
    if (section !== 'content') return
    let cancelled = false
    setLoadingSegments(true)
    setSegmentsError(null)
    listSegments()
      .then((data) => {
        if (cancelled) return
        setSegments(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSegmentsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingSegments(false)
      })
    return () => {
      cancelled = true
    }
  }, [section])

  useEffect(() => {
    if (section !== 'content') return
    if (contentTab !== 'geozones' && contentTab !== 'arobjects') return
    let cancelled = false
    setLoadingGeoZones(true)
    setGeoZonesError(null)
    listGeoZones()
      .then((data) => {
        if (cancelled) return
        setGeoZones(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setGeoZonesError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingGeoZones(false)
      })
    return () => {
      cancelled = true
    }
  }, [section, contentTab])

  useEffect(() => {
    if (section !== 'content') return
    if (contentTab !== 'arobjects') return
    let cancelled = false
    setLoadingARObjects(true)
    setARObjectsError(null)
    listARObjects()
      .then((data) => {
        if (cancelled) return
        setARObjects(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setARObjectsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingARObjects(false)
      })
    return () => {
      cancelled = true
    }
  }, [section, contentTab])

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
    setShowCreateKey(false)
    setCreateKeyError(null)
  }, [selectedKeyRuleId, section])

  useEffect(() => {
    const k = selectedKeyRule()
    if (!k) {
      setSavingKeyError(null)
      setSavingKeyNotice(null)
      return
    }
    setKeyEditConsumable(k.isConsumable)
    setKeyEditStackLimit(String(k.stackLimit))
    setKeyEditSortOrder(String(k.sortOrder))
    setKeyEditTransferForbidden(k.transferForbidden)
    setKeyEditSaleForbidden(k.saleForbidden)
    setKeyEditTradeForbidden(k.tradeForbidden)
    setSavingKeyError(null)
    setSavingKeyNotice(null)
  }, [selectedKeyRuleId, keyRules])

  useEffect(() => {
    const s = selectedSegment()
    if (!s) {
      setSegmentError(null)
      setSegmentNotice(null)
      return
    }
    setSegmentTitle(s.title)
    setSegmentSlug(s.slug)
    setSegmentDescription(s.description ?? '')
    setSegmentChapterId(s.chapterId)
    setSegmentSortOrder(String(s.sortOrder))
    setSegmentContentJson(JSON.stringify(s.content ?? {}, null, 2))
    setSegmentMissions(
      s.linkedMissions.map((link) => ({
        missionId: link.missionId,
        sortOrder: String(link.sortOrder),
      })),
    )
    setSegmentError(null)
    setSegmentNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSegmentId, segments])

  useEffect(() => {
    const z = selectedGeoZone()
    if (!z) {
      setGeoZoneError(null)
      setGeoZoneNotice(null)
      return
    }
    setGeoZoneSlug(z.slug)
    setGeoZoneTitle(z.title)
    setGeoZoneDescription(z.description ?? '')
    setGeoZoneSortOrder(String(z.sortOrder))
    setGeoZoneRadiusMeters(z.radiusMeters === null ? '' : String(z.radiusMeters))
    setGeoZoneSearchRadiusMeters(z.searchRadiusMeters === null ? '' : String(z.searchRadiusMeters))
    setGeoZoneMaxAccuracy(z.maxLocationAccuracyMeters === null ? '' : String(z.maxLocationAccuracyMeters))
    setGeoZoneMinPresence(String(z.minimumPresenceSeconds))
    setGeoZoneStatus(z.status)
    const lc = z.locationConstraints ?? {}
    setGeoZoneAvoidBuildings(lc.avoid_buildings ?? false)
    setGeoZoneAvoidWater(lc.avoid_water ?? false)
    setGeoZoneAvoidRoads(lc.avoid_roads ?? false)
    setGeoZoneAvoidPrivate(lc.avoid_private ?? false)
    setGeoZoneError(null)
    setGeoZoneNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGeoZoneId, geoZones])

  useEffect(() => {
    const o = selectedARObject()
    if (!o) {
      setARObjectError(null)
      setARObjectNotice(null)
      return
    }
    setARObjectSlug(o.slug)
    setARObjectTitle(o.title)
    setARObjectDescription(o.description ?? '')
    setARObjectGeoZoneId(o.geoZoneId)
    setARObjectObjectType(o.objectType)
    setARObjectAssetUri(o.assetUri)
    setARObjectAssetMimeType(o.assetMimeType ?? '')
    setARObjectScenePreset(o.scenePreset ?? '')
    setARObjectInstructionText(o.instructionText ?? '')
    setARObjectScaleMeters(String(o.scaleMeters))
    setARObjectOrientation(o.orientation)
    setARObjectSortOrder(String(o.sortOrder))
    setARObjectStatus(o.status)
    setARObjectError(null)
    setARObjectNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedARObjectId, arObjects])

  useEffect(() => {
    setShowCreateSegment(false)
    setSegmentError(null)
  }, [selectedSegmentId, section])

  useEffect(() => {
    setShowCreateGeoZone(false)
    setGeoZoneError(null)
  }, [selectedGeoZoneId, section, contentTab])

  useEffect(() => {
    setShowCreateARObject(false)
    setARObjectError(null)
  }, [selectedARObjectId, section, contentTab])

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

  useEffect(() => {
    if (section !== 'content') return
    let cancelled = false
    setLoadingMissionsForLink(true)
    setMissionsForLinkError(null)
    listAdminMissions()
      .then((data) => {
        if (cancelled) return
        setMissionsForLink(
          data.map((m) => ({
            id: m.id,
            slug: m.slug,
            title: m.title,
            chapterId: m.chapterId,
            status: m.status,
          })),
        )
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMissionsForLinkError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingMissionsForLink(false)
      })
    return () => {
      cancelled = true
    }
  }, [section])

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

  const groupedSettings = useMemo(() => {
    const groups = new Map<string, AdminSystemSetting[]>()
    for (const s of settings) {
      const arr = groups.get(s.category) ?? []
      arr.push(s)
      groups.set(s.category, arr)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [settings])

  function selectedAdmin(): AdminUserFull | null {
    if (selectedAdminId === null) return null
    return adminsList.find((a) => a.id === selectedAdminId) ?? null
  }

  function selectedKeyRule(): KeyRule | null {
    if (selectedKeyRuleId === null) return null
    return keyRules.find((k) => k.id === selectedKeyRuleId) ?? null
  }

  function selectedSegment(): AdminSegment | null {
    if (selectedSegmentId === null) return null
    return segments.find((s) => s.id === selectedSegmentId) ?? null
  }

  function selectedGeoZone(): AdminGeoZone | null {
    if (selectedGeoZoneId === null) return null
    return geoZones.find((z) => z.id === selectedGeoZoneId) ?? null
  }

  function selectedARObject(): AdminARObject | null {
    if (selectedARObjectId === null) return null
    return arObjects.find((o) => o.id === selectedARObjectId) ?? null
  }

  function buildARObjectPayloadCommon() {
    const slug = arObjectSlug.trim()
    const title = arObjectTitle.trim()
    if (slug.length < 3) throw new Error('Slug минимум 3 символа.')
    if (title.length < 1) throw new Error('Название обязательно.')
    const geoZoneId = arObjectGeoZoneId.trim()
    if (geoZoneId.length < 1) throw new Error('GeoZone обязателен.')
    const objectType = arObjectObjectType.trim()
    if (objectType.length < 1) throw new Error('Тип объекта обязателен.')
    const assetUri = arObjectAssetUri.trim()
    if (assetUri.length < 1) throw new Error('URL ассета обязателен.')
    const scale = Number.parseFloat(arObjectScaleMeters)
    if (!Number.isFinite(scale) || scale <= 0 || scale > 10) {
      throw new Error('Размер (scale) — число в диапазоне (0, 10].')
    }
    const sortOrder = Number.parseInt(arObjectSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      throw new Error('Порядок сортировки — целое ≥ 0.')
    }
    return { slug, title, geoZoneId, objectType, assetUri, scale, sortOrder }
  }

  async function handleCreateARObject() {
    setSavingARObject(true)
    setARObjectError(null)
    setARObjectNotice(null)
    try {
      const p = buildARObjectPayloadCommon()
      const created = await createARObject({
        slug: p.slug,
        title: p.title,
        description: arObjectDescription.trim() || null,
        sort_order: p.sortOrder,
        geo_zone_id: p.geoZoneId,
        object_type: p.objectType,
        asset_uri: p.assetUri,
        asset_mime_type: arObjectAssetMimeType.trim() || null,
        scene_preset: arObjectScenePreset.trim() || null,
        instruction_text: arObjectInstructionText.trim() || null,
        scale_meters: p.scale,
        orientation: arObjectOrientation,
      })
      setARObjects((prev) => [...prev, created])
      setSelectedARObjectId(created.id)
      setShowCreateARObject(false)
      setARObjectNotice('AR-объект создан.')
    } catch (err) {
      setARObjectError((err as Error).message)
    } finally {
      setSavingARObject(false)
    }
  }

  async function handleSaveARObject() {
    const o = selectedARObject()
    if (!o) return
    setSavingARObject(true)
    setARObjectError(null)
    setARObjectNotice(null)
    try {
      const p = buildARObjectPayloadCommon()
      const updated = await updateARObject(o.id, {
        slug: p.slug,
        title: p.title,
        description: arObjectDescription.trim() || null,
        status: arObjectStatus,
        sort_order: p.sortOrder,
        geo_zone_id: p.geoZoneId,
        object_type: p.objectType,
        asset_uri: p.assetUri,
        asset_mime_type: arObjectAssetMimeType.trim() || null,
        scene_preset: arObjectScenePreset.trim() || null,
        instruction_text: arObjectInstructionText.trim() || null,
        scale_meters: p.scale,
        orientation: arObjectOrientation,
      })
      setARObjects((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setARObjectNotice('Сохранено.')
    } catch (err) {
      setARObjectError((err as Error).message)
    } finally {
      setSavingARObject(false)
    }
  }

  function handleShowCreateARObject() {
    setShowCreateARObject(true)
    setARObjectSlug('')
    setARObjectTitle('')
    setARObjectDescription('')
    setARObjectGeoZoneId('')
    setARObjectObjectType('cube')
    setARObjectAssetUri('')
    setARObjectAssetMimeType('')
    setARObjectScenePreset('')
    setARObjectInstructionText('')
    setARObjectScaleMeters('1.0')
    setARObjectOrientation('free')
    setARObjectSortOrder('0')
    setARObjectStatus('draft')
    setARObjectError(null)
    setARObjectNotice(null)
    setSelectedARObjectId(null)
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
    const stackLimit = Number.parseInt(newKeyStackLimit, 10)
    if (!Number.isFinite(stackLimit) || stackLimit < 1) {
      setCreateKeyError('Стак-лимит должен быть целым числом ≥ 1.')
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
        stack_limit: stackLimit,
      })
      setKeyRules((prev) => [...prev, created])
      setSelectedKeyRuleId(created.id)
      setShowCreateKey(false)
      setNewKeyTitle('')
      setNewKeyCode('')
      setNewKeySymbol('')
      setNewKeyConsumable(true)
      setNewKeyStackLimit('1')
    } catch (err) {
      setCreateKeyError((err as Error).message)
    } finally {
      setCreatingKey(false)
    }
  }

  async function handleSaveKey() {
    const k = selectedKeyRule()
    if (!k) return
    const stackLimit = Number.parseInt(keyEditStackLimit, 10)
    if (!Number.isFinite(stackLimit) || stackLimit < 1) {
      setSavingKeyError('Стак-лимит должен быть ≥ 1.')
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
        stack_limit: stackLimit,
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

  function parseSegmentContentJson(): Record<string, unknown> {
    try {
      const parsed = JSON.parse(segmentContentJson)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        throw new Error('Content: ожидается JSON-объект.')
      }
      return parsed as Record<string, unknown>
    } catch (err) {
      throw new Error(
        err instanceof Error ? `Content: ${err.message}` : 'Content: некорректный JSON.',
      )
    }
  }

  async function handleCreateSegment() {
    const title = segmentTitle.trim()
    const slug = segmentSlug.trim()
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название сегмента обязательно.'); return }
    if (slug.length < 3) { setSegmentError('Slug минимум 3 символа.'); return }
    if (chapterId.length < 1) { setSegmentError('Chapter ID обязателен.'); return }
    let content: Record<string, unknown>
    try { content = parseSegmentContentJson() }
    catch (err) { setSegmentError((err as Error).message); return }
    const sortOrder = Number.parseInt(segmentSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) { setSegmentError('Порядок сортировки — целое ≥ 0.'); return }

    setSavingSegment(true); setSegmentError(null)
    try {
      const created = await createSegment({
        chapter_id: chapterId,
        slug,
        title,
        description: segmentDescription.trim() || null,
        content,
        sort_order: sortOrder,
        linked_missions: segmentMissions
          .filter((m) => m.missionId.trim().length > 0)
          .map((m) => ({ mission_id: m.missionId.trim(), sort_order: Number(m.sortOrder || 0) })),
      })
      setSegments((prev) => [...prev, created])
      setSelectedSegmentId(created.id)
      setShowCreateSegment(false)
      setSegmentNotice('Сегмент создан.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setSavingSegment(false) }
  }

  async function handleSaveSegment() {
    const s = selectedSegment()
    if (!s) return
    const title = segmentTitle.trim()
    const slug = segmentSlug.trim()
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название сегмента обязательно.'); return }
    if (slug.length < 3) { setSegmentError('Slug минимум 3 символа.'); return }
    if (chapterId.length < 1) { setSegmentError('Chapter ID обязателен.'); return }
    let content: Record<string, unknown>
    try { content = parseSegmentContentJson() }
    catch (err) { setSegmentError((err as Error).message); return }
    const sortOrder = Number.parseInt(segmentSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) { setSegmentError('Порядок сортировки — целое ≥ 0.'); return }

    setSavingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await updateSegment(s.id, {
        chapter_id: chapterId,
        slug,
        title,
        description: segmentDescription.trim() || null,
        content,
        sort_order: sortOrder,
        linked_missions: segmentMissions
          .filter((m) => m.missionId.trim().length > 0)
          .map((m) => ({ mission_id: m.missionId.trim(), sort_order: Number(m.sortOrder || 0) })),
      })
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сохранено.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setSavingSegment(false) }
  }

  async function handlePublishSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await publishSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент опубликован.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  async function handleUnpublishSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await unpublishSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент снят с публикации.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  async function handleArchiveSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await archiveSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент архивирован.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  function buildGeoZonePayloadCommon() {
    const slug = geoZoneSlug.trim()
    const title = geoZoneTitle.trim()
    if (slug.length < 3) throw new Error('Slug минимум 3 символа.')
    if (title.length < 1) throw new Error('Название обязательно.')

    const sortOrder = Number.parseInt(geoZoneSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      throw new Error('Порядок сортировки — целое ≥ 0.')
    }

    const radius = Number.parseInt(geoZoneRadiusMeters, 10)
    if (!Number.isFinite(radius) || radius <= 0) {
      throw new Error('Размер зоны (radius) — целое > 0.')
    }

    const searchRadius = Number.parseInt(geoZoneSearchRadiusMeters, 10)
    if (!Number.isFinite(searchRadius) || searchRadius <= 0) {
      throw new Error('Радиус поиска — целое > 0.')
    }

    const minPresence = Number.parseInt(geoZoneMinPresence, 10)
    if (!Number.isFinite(minPresence) || minPresence < 0) {
      throw new Error('Минимальное время присутствия — целое ≥ 0.')
    }

    const maxAccRaw = geoZoneMaxAccuracy.trim()
    const maxAcc = maxAccRaw === '' ? null : Number.parseInt(maxAccRaw, 10)
    if (maxAcc !== null && (!Number.isFinite(maxAcc) || maxAcc < 0)) {
      throw new Error('Точность GPS — целое ≥ 0 или пусто.')
    }

    const locationConstraints: Record<string, boolean> = {}
    if (geoZoneAvoidBuildings) locationConstraints.avoid_buildings = true
    if (geoZoneAvoidWater) locationConstraints.avoid_water = true
    if (geoZoneAvoidRoads) locationConstraints.avoid_roads = true
    if (geoZoneAvoidPrivate) locationConstraints.avoid_private = true

    return { slug, title, sortOrder, radius, searchRadius, minPresence, maxAcc, locationConstraints }
  }

  async function handleCreateGeoZone() {
    setSavingGeoZone(true); setGeoZoneError(null); setGeoZoneNotice(null)
    try {
      const p = buildGeoZonePayloadCommon()
      const created = await createGeoZone({
        slug: p.slug,
        title: p.title,
        description: geoZoneDescription.trim() || null,
        zone_type: 'radius',
        sort_order: p.sortOrder,
        radius_meters: p.radius,
        search_radius_meters: p.searchRadius,
        minimum_presence_seconds: p.minPresence,
        max_location_accuracy_meters: p.maxAcc,
        location_constraints: p.locationConstraints,
      })
      setGeoZones((prev) => [...prev, created])
      setSelectedGeoZoneId(created.id)
      setShowCreateGeoZone(false)
      setGeoZoneNotice('Шаблон создан.')
    } catch (err) { setGeoZoneError((err as Error).message) }
    finally { setSavingGeoZone(false) }
  }

  async function handleSaveGeoZone() {
    const z = selectedGeoZone()
    if (!z) return
    setSavingGeoZone(true); setGeoZoneError(null); setGeoZoneNotice(null)
    try {
      const p = buildGeoZonePayloadCommon()
      const updated = await updateGeoZone(z.id, {
        slug: p.slug,
        title: p.title,
        description: geoZoneDescription.trim() || null,
        zone_type: 'radius',
        status: geoZoneStatus,
        sort_order: p.sortOrder,
        radius_meters: p.radius,
        search_radius_meters: p.searchRadius,
        minimum_presence_seconds: p.minPresence,
        max_location_accuracy_meters: p.maxAcc,
        location_constraints: p.locationConstraints,
      })
      setGeoZones((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setGeoZoneNotice('Сохранено.')
    } catch (err) { setGeoZoneError((err as Error).message) }
    finally { setSavingGeoZone(false) }
  }

  function handleShowCreateGeoZone() {
    setShowCreateGeoZone(true)
    setGeoZoneSlug('')
    setGeoZoneTitle('')
    setGeoZoneDescription('')
    setGeoZoneSortOrder('0')
    setGeoZoneRadiusMeters('')
    setGeoZoneSearchRadiusMeters('')
    setGeoZoneMaxAccuracy('')
    setGeoZoneMinPresence('0')
    setGeoZoneStatus('draft')
    setGeoZoneAvoidBuildings(true)
    setGeoZoneAvoidWater(true)
    setGeoZoneAvoidRoads(true)
    setGeoZoneAvoidPrivate(true)
    setGeoZoneError(null)
    setGeoZoneNotice(null)
    setSelectedGeoZoneId(null)
  }

  function addSegmentMissionLink() {
    setSegmentMissions((prev) => [...prev, { missionId: '', sortOrder: '0' }])
  }

  function changeSegmentMissionLink(index: number, missionId: string) {
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, missionId } : m)),
    )
  }

  function changeSegmentMissionSort(index: number, sortOrder: string) {
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, sortOrder } : m)),
    )
  }

  function removeSegmentMissionLink(index: number) {
    setSegmentMissions((prev) => prev.filter((_, i) => i !== index))
  }

  function handleShowCreateSegment() {
    setShowCreateSegment(true)
    setSegmentTitle('')
    setSegmentSlug('')
    setSegmentDescription('')
    setSegmentChapterId('')
    setSegmentSortOrder('0')
    setSegmentContentJson('{}')
    setSegmentMissions([])
    setSegmentError(null)
    setSegmentNotice(null)
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

  async function handleTogglePermission(
    target: AdminUserFull,
    permissionCode: string,
    currentlyGranted: boolean,
  ) {
    if (target.isSuperAdmin) return
    setPermSaving(permissionCode)
    setPermError(null)
    try {
      const updated = currentlyGranted
        ? await revokePermission(target.id, permissionCode)
        : await grantPermission(target.id, {
            permission_code: permissionCode,
            reason: permReason.trim() || undefined,
          })
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
    } catch (err) {
      setPermError((err as Error).message)
    } finally {
      setPermSaving(null)
    }
  }

  async function handleCreateAdmin() {
    const username = newAdminUsername.trim()
    if (username.length < 3) {
      setCreateAdminError('Username минимум 3 символа.')
      return
    }
    if (newAdminPassword.length < 12) {
      setCreateAdminError('Пароль минимум 12 символов.')
      return
    }
    setCreatingAdmin(true)
    setCreateAdminError(null)
    try {
      const created = await createAdmin({
        username,
        password: newAdminPassword,
      })
      setAdminsList((prev) =>
        [...prev, created].sort((a, b) =>
          a.username.localeCompare(b.username),
        ),
      )
      setSelectedAdminId(created.id)
      setShowCreateAdmin(false)
      setNewAdminUsername('')
      setNewAdminPassword('')
    } catch (err) {
      setCreateAdminError((err as Error).message)
    } finally {
      setCreatingAdmin(false)
    }
  }

  async function handleDeactivate(target: AdminUserFull) {
    const reason = deactivateReason.trim()
    if (reason.length < 3) {
      setActiveError('Причина минимум 3 символа.')
      return
    }
    setTogglingActive(true)
    setActiveError(null)
    try {
      const updated = await deactivateAdmin(target.id, reason)
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
      setDeactivateReason('')
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setTogglingActive(false)
    }
  }

  async function handleReactivate(target: AdminUserFull) {
    setTogglingActive(true)
    setActiveError(null)
    try {
      const updated = await reactivateAdmin(target.id)
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setTogglingActive(false)
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
      )}

      {section === 'admins' && (admin?.isSuperAdmin ?? false) && (
        <div className="admin-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-primary"
              onClick={() => {
                setShowCreateAdmin(true)
                setCreateAdminError(null)
                setNewAdminUsername('')
                setNewAdminPassword('')
              }}
            >
              + Новый админ
            </button>

            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedAdminId(null)
                setAdminsList([])
                setAdminsError(null)
                setLoadingAdmins(true)
                listAdmins()
                  .then(setAdminsList)
                  .catch((err: Error) => setAdminsError(err.message))
                  .finally(() => setLoadingAdmins(false))
              }}
              disabled={loadingAdmins}
            >
              {loadingAdmins ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {adminsError && (
              <p className="admin-alert admin-error">{adminsError}</p>
            )}

            <div className="admin-mission-list">
              {adminsList.map((a) => (
                <button
                  className={`admin-mission-row ${selectedAdminId === a.id ? 'is-active' : ''}`}
                  key={a.id}
                  onClick={() => setSelectedAdminId(a.id)}
                >
                  {a.isSuperAdmin && (
                    <span className="admin-badge admin-badge-super">super</span>
                  )}
                  {!a.isActive && (
                    <span className="admin-badge admin-badge-inactive">
                      выключен
                    </span>
                  )}
                  {a.isDeleted && (
                    <span className="admin-badge admin-badge-deleted">
                      удалён
                    </span>
                  )}
                  <strong>{a.username}</strong>
                  <small>
                    {a.permissions.filter((p) => p.isActive).length} прав
                  </small>
                </button>
              ))}
              {!loadingAdmins && adminsList.length === 0 && !adminsError && (
                <p className="admin-muted">Админов нет.</p>
              )}
            </div>
          </aside>

          <section className="admin-editor">
            {showCreateAdmin ? (
              <>
                <div className="admin-editor-title">
                  <h2>Новый администратор</h2>
                </div>

                {createAdminError && (
                  <p className="admin-alert admin-error">
                    {createAdminError}
                  </p>
                )}

                <label className="admin-field">
                  <span>Username (3–64, строчные буквы, цифры, . _ -)</span>
                  <input
                    type="text"
                    value={newAdminUsername}
                    onChange={(e) => setNewAdminUsername(e.target.value)}
                    maxLength={64}
                    disabled={creatingAdmin}
                  />
                </label>

                <label className="admin-field">
                  <span>Пароль (минимум 12 символов)</span>
                  <input
                    type="password"
                    value={newAdminPassword}
                    onChange={(e) => setNewAdminPassword(e.target.value)}
                    maxLength={1024}
                    disabled={creatingAdmin}
                  />
                </label>

                <div className="admin-actions">
                  <button
                    className="admin-primary"
                    onClick={handleCreateAdmin}
                    disabled={creatingAdmin}
                  >
                    {creatingAdmin ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateAdmin(false)}
                    disabled={creatingAdmin}
                  >
                    Отмена
                  </button>
                </div>

                <p className="admin-muted" style={{ marginTop: 24 }}>
                  Новый админ создаётся без прав. Права выдаются после
                  создания. Учётная запись всегда обычного админа (супер-админ
                  создаётся только через отдельную процедуру).
                </p>
              </>
            ) : selectedAdmin() === null ? (
              <p className="admin-muted">Выберите администратора слева.</p>
            ) : (
              (() => {
                const a = selectedAdmin()!
                return (
                  <>
                    <div className="admin-editor-title">
                      <h2>{a.username}</h2>
                      {a.isSuperAdmin && (
                        <span className="admin-badge admin-badge-super">
                          super
                        </span>
                      )}
                      {!a.isActive && (
                        <span className="admin-badge admin-badge-inactive">
                          выключен
                        </span>
                      )}
                      {a.isDeleted && (
                        <span className="admin-badge admin-badge-deleted">
                          удалён
                        </span>
                      )}
                    </div>

                    {!a.isSuperAdmin && (
                      <div style={{ marginTop: 16 }}>
                        {activeError && (
                          <p className="admin-alert admin-error">
                            {activeError}
                          </p>
                        )}
                        {a.isActive ? (
                          <div className="admin-field">
                            <span>
                              Деактивация (админ сохранится в БД, но не сможет
                              войти)
                            </span>
                            <input
                              type="text"
                              value={deactivateReason}
                              onChange={(e) =>
                                setDeactivateReason(e.target.value)
                              }
                              placeholder="Причина (мин. 3 символа)"
                              maxLength={4000}
                              disabled={togglingActive}
                            />
                            <div
                              className="admin-actions"
                              style={{ marginTop: 8 }}
                            >
                              <button
                                className="admin-secondary"
                                onClick={() => handleDeactivate(a)}
                                disabled={
                                  togglingActive ||
                                  deactivateReason.trim().length < 3
                                }
                              >
                                {togglingActive
                                  ? 'Выключение…'
                                  : 'Выключить доступ'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="admin-actions">
                            <button
                              className="admin-primary"
                              onClick={() => handleReactivate(a)}
                              disabled={togglingActive}
                            >
                              {togglingActive
                                ? 'Включение…'
                                : 'Включить доступ'}
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    <p className="admin-muted">
                      <b>ID:</b> <code>{a.id}</code>
                    </p>
                    <p className="admin-muted">
                      <b>Создан:</b> {a.createdAt ?? '—'} ·{' '}
                      <b>Последний вход:</b> {a.lastLoginAt ?? '—'}
                    </p>
                    {a.deactivationReason && (
                      <p className="admin-muted">
                        <b>Причина деактивации:</b> {a.deactivationReason}
                      </p>
                    )}

                    <h3 style={{ marginTop: 24 }}>Права</h3>

                    {a.isSuperAdmin && (
                      <p className="admin-alert admin-notice">
                        Супер-админ имеет все права. Индивидуальные permissions
                        не настраиваются.
                      </p>
                    )}

                    {!a.isSuperAdmin && (
                      <>
                        {permError && (
                          <p className="admin-alert admin-error">
                            {permError}
                          </p>
                        )}

                        <label className="admin-field">
                          <span>
                            Причина изменения (для аудита, необязательно)
                          </span>
                          <input
                            type="text"
                            value={permReason}
                            onChange={(e) =>
                              setPermReason(e.target.value)
                            }
                            maxLength={200}
                            disabled={permSaving !== null}
                          />
                        </label>

                        <div className="admin-permissions">
                          {PERMISSION_CATALOG.map(
                            (p: PermissionCatalogEntry) => {
                              const grant = a.permissions.find(
                                (g) =>
                                  g.permissionCode === p.code && g.isActive,
                              )
                              const isSaving = permSaving === p.code
                              return (
                                <label
                                  key={p.code}
                                  className="admin-permission-row"
                                >
                                  <input
                                    type="checkbox"
                                    checked={!!grant}
                                    onChange={() =>
                                      handleTogglePermission(
                                        a,
                                        p.code,
                                        !!grant,
                                      )
                                    }
                                    disabled={isSaving}
                                  />
                                  <span className="admin-permission-title">
                                    {p.title}
                                    {isSaving && ' …'}
                                  </span>
                                  <code className="admin-permission-code">
                                    {p.code}
                                  </code>
                                  {grant &&
                                    grant.executionMode !== 'direct' && (
                                      <span className="admin-badge admin-badge-approval">
                                        {grant.executionMode}
                                      </span>
                                    )}
                                </label>
                              )
                            },
                          )}
                        </div>
                      </>
                    )}
                  </>
                )
              })()
            )}
          </section>
        </div>
      )}

      {section === 'keys' && (
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
                setNewKeyStackLimit('1')
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
                  <span>Стак-лимит (сколько в инвентаре максимум)</span>
                  <input
                    type="number"
                    min={1}
                    value={newKeyStackLimit}
                    onChange={(e) => setNewKeyStackLimit(e.target.value)}
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
                      <span>Стак-лимит</span>
                      <input
                        type="number"
                        min={1}
                        value={keyEditStackLimit}
                        onChange={(e) => setKeyEditStackLimit(e.target.value)}
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
        <div className="admin-layout">
          <aside className="admin-sidebar">
            {contentTab === 'segments' && (
              <>
                <button
                  className="admin-primary"
                  onClick={handleShowCreateSegment}
                  disabled={!canWrite}
                >
                  + Новый сегмент
                </button>
                <button
                  className="admin-secondary"
                  onClick={() => {
                    setLoadingSegments(true)
                    setSegmentsError(null)
                    listSegments()
                      .then((data) => setSegments(data))
                      .catch((err: Error) => setSegmentsError(err.message))
                      .finally(() => setLoadingSegments(false))
                  }}
                >
                  ↻ Обновить список
                </button>

                {segmentsError && (
                  <p className="admin-alert admin-error">{segmentsError}</p>
                )}

                <div className="admin-mission-list">
                  {segments.map((segment) => (
                    <button
                      key={segment.id}
                      className={selectedSegmentId === segment.id ? 'is-active' : ''}
                      onClick={() => setSelectedSegmentId(segment.id)}
                    >
                      <strong>{segment.title}</strong>
                      <small>{segment.slug}</small>
                      <span className={`admin-status admin-status-${segment.status}`}>
                        {segment.status}
                      </span>
                    </button>
                  ))}
                  {!loadingSegments && segments.length === 0 && !segmentsError && (
                    <p className="admin-muted">Сегментов нет.</p>
                  )}
                </div>
              </>
            )}

            {contentTab === 'geozones' && (
              <>
                <button
                  className="admin-primary"
                  onClick={handleShowCreateGeoZone}
                  disabled={!canWrite}
                >
                  + Новая геозона
                </button>
                <button
                  className="admin-secondary"
                  onClick={() => {
                    setLoadingGeoZones(true)
                    setGeoZonesError(null)
                    listGeoZones()
                      .then((data) => setGeoZones(data))
                      .catch((err: Error) => setGeoZonesError(err.message))
                      .finally(() => setLoadingGeoZones(false))
                  }}
                >
                  ↻ Обновить список
                </button>

                {geoZonesError && (
                  <p className="admin-alert admin-error">{geoZonesError}</p>
                )}

                <div className="admin-mission-list">
                  {geoZones.map((zone) => (
                    <button
                      key={zone.id}
                      className={selectedGeoZoneId === zone.id ? 'is-active' : ''}
                      onClick={() => setSelectedGeoZoneId(zone.id)}
                    >
                      <strong>{zone.title}</strong>
                      <small>{zone.slug} · {zone.zoneType}</small>
                      <span className={`admin-status admin-status-${zone.status}`}>
                        {zone.status}
                      </span>
                    </button>
                  ))}
                  {!loadingGeoZones && geoZones.length === 0 && !geoZonesError && (
                    <p className="admin-muted">Геозон нет.</p>
                  )}
                </div>
              </>
            )}

            {contentTab === 'arobjects' && (
              <>
                <button
                  className="admin-primary"
                  onClick={handleShowCreateARObject}
                  disabled={!canWrite}
                >
                  + Новый AR-объект
                </button>
                <button
                  className="admin-secondary"
                  onClick={() => {
                    setLoadingARObjects(true)
                    setARObjectsError(null)
                    listARObjects()
                      .then((data) => setARObjects(data))
                      .catch((err: Error) => setARObjectsError(err.message))
                      .finally(() => setLoadingARObjects(false))
                  }}
                >
                  ↻ Обновить список
                </button>

                {arObjectsError && (
                  <p className="admin-alert admin-error">{arObjectsError}</p>
                )}

                <div className="admin-mission-list">
                  {arObjects.map((o) => (
                    <button
                      key={o.id}
                      className={selectedARObjectId === o.id ? 'is-active' : ''}
                      onClick={() => setSelectedARObjectId(o.id)}
                    >
                      <strong>{o.title}</strong>
                      <small>{o.slug} · {o.objectType}</small>
                      <span className={`admin-status admin-status-${o.status}`}>
                        {o.status}
                      </span>
                    </button>
                  ))}
                  {!loadingARObjects && arObjects.length === 0 && !arObjectsError && (
                    <p className="admin-muted">AR-объектов нет.</p>
                  )}
                </div>
              </>
            )}
          </aside>

          <section className="admin-editor">
            <div className="admin-editor-title">
              <div>
                <p className="admin-kicker">КОНТЕНТ</p>
                <h2>Управление контентом</h2>
              </div>
            </div>

            <nav className="admin-nav" style={{ marginBottom: '1rem' }}>
              <button
                className={contentTab === 'segments' ? 'is-active' : ''}
                onClick={() => setContentTab('segments')}
              >
                Сегменты
              </button>
              <button
                className={contentTab === 'geozones' ? 'is-active' : ''}
                onClick={() => setContentTab('geozones')}
              >
                Геозоны
              </button>
              <button
                className={contentTab === 'arobjects' ? 'is-active' : ''}
                onClick={() => setContentTab('arobjects')}
              >
                AR-объекты
              </button>
            </nav>

            {contentTab === 'segments' && (
              <>
                <div className="admin-editor-title">
                  <div>
                    <p className="admin-kicker">
                      {showCreateSegment
                        ? 'НОВЫЙ СЕГМЕНТ'
                        : selectedSegment() ? selectedSegment()!.id : '—'}
                    </p>
                    <h2>
                      {showCreateSegment
                        ? 'Создание сегмента'
                        : selectedSegment() ? 'Редактирование сегмента' : 'Редактор сегмента'}
                    </h2>
                    {selectedSegment() && !showCreateSegment && (
                      <span
                        className={`admin-status admin-status-${selectedSegment()!.status}`}
                      >
                        {selectedSegment()!.status}
                      </span>
                    )}
                  </div>
                </div>

                {segmentError && (
                  <p className="admin-alert admin-error">{segmentError}</p>
                )}
                {segmentNotice && (
                  <p className="admin-alert admin-notice">{segmentNotice}</p>
                )}

                {(!showCreateSegment && selectedSegment() === null) ? (
                  <p className="admin-muted">
                    Выберите сегмент слева или создайте новый.
                  </p>
                ) : (
                  <>
                    <label className="admin-field">
                      <span>Название сегмента</span>
                      <input
                        type="text"
                        value={segmentTitle}
                        onChange={(e) => setSegmentTitle(e.target.value)}
                        disabled={!canWrite}
                      />
                    </label>
                    <label className="admin-field">
                      <span>Slug</span>
                      <input
                        type="text"
                        value={segmentSlug}
                        onChange={(e) => setSegmentSlug(e.target.value)}
                        disabled={!canWrite}
                      />
                    </label>
                    <label className="admin-field">
                      <span>Chapter ID</span>
                      <input
                        type="text"
                        value={segmentChapterId}
                        onChange={(e) => setSegmentChapterId(e.target.value)}
                        disabled={!canWrite}
                      />
                    </label>
                    <label className="admin-field">
                      <span>Описание</span>
                      <textarea
                        rows={3}
                        value={segmentDescription}
                        onChange={(e) => setSegmentDescription(e.target.value)}
                        disabled={!canWrite}
                      />
                    </label>
                    <label className="admin-field">
                      <span>Порядок сортировки (меньше = выше)</span>
                      <input
                        type="number"
                        min={0}
                        value={segmentSortOrder}
                        onChange={(e) => setSegmentSortOrder(e.target.value)}
                        disabled={!canWrite}
                      />
                    </label>
                    <label className="admin-field">
                      <span>Content (JSON)</span>
                      <textarea
                        rows={8}
                        className="admin-code"
                        value={segmentContentJson}
                        onChange={(e) => setSegmentContentJson(e.target.value)}
                        disabled={!canWrite}
                        spellCheck={false}
                      />
                    </label>


                    <section>
                      <h3 style={{ marginTop: 24 }}>Привязанные миссии</h3>

                      {loadingMissionsForLink && (
                        <p className="admin-muted">Загрузка миссий…</p>
                      )}
                      {missionsForLinkError && (
                        <p className="admin-alert admin-error">
                          {missionsForLinkError}
                        </p>
                      )}

                      <button
                        className="admin-secondary"
                        onClick={addSegmentMissionLink}
                        disabled={!canWrite}
                      >
                        + Добавить миссию
                      </button>

                      {segmentMissions.map((link, index) => (
                        <div key={index} className="admin-link-row">
                          <select
                            value={link.missionId}
                            disabled={!canWrite}
                            onChange={(e) =>
                              changeSegmentMissionLink(index, e.target.value)
                            }
                          >
                            {link.missionId === '' && (
                              <option value="" disabled>
                                Выберите миссию…
                              </option>
                            )}
                            {missionsForLink.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.title} · {m.slug} [{m.status}]
                              </option>
                            ))}
                          </select>
                          <input
                            type="number"
                            value={link.sortOrder}
                            disabled={!canWrite}
                            onChange={(e) =>
                              changeSegmentMissionSort(index, e.target.value)
                            }
                          />
                          <button
                            className="admin-danger"
                            onClick={() => removeSegmentMissionLink(index)}
                            disabled={!canWrite}
                          >
                            Удалить
                          </button>
                        </div>
                      ))}

                      {segmentMissions.length === 0 && (
                        <p className="admin-muted">
                          Миссии не привязаны. Публикация требует ≥1 published
                          миссии той же главы.
                        </p>
                      )}
                    </section>

                    <div className="admin-actions">
                      {showCreateSegment ? (
                        <>
                          <button
                            className="admin-primary"
                            onClick={handleCreateSegment}
                            disabled={!canWrite || savingSegment}
                          >
                            {savingSegment ? 'Создание…' : 'Создать'}
                          </button>
                          <button
                            className="admin-secondary"
                            onClick={() => setShowCreateSegment(false)}
                            disabled={savingSegment}
                          >
                            Отмена
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="admin-primary"
                            onClick={handleSaveSegment}
                            disabled={!canWrite || savingSegment}
                          >
                            {savingSegment ? 'Сохранение…' : 'Сохранить'}
                          </button>

                          {selectedSegment()?.status === 'draft' && (
                            <button
                              className="admin-publish"
                              onClick={handlePublishSegment}
                              disabled={!canWrite || publishingSegment}
                            >
                              {publishingSegment ? 'Публикация…' : 'Опубликовать'}
                            </button>
                          )}

                          {selectedSegment()?.status === 'published' && (
                            <button
                              className="admin-secondary"
                              onClick={handleUnpublishSegment}
                              disabled={!canWrite || publishingSegment}
                            >
                              Снять с публикации
                            </button>
                          )}

                          {selectedSegment()?.status === 'published' && (
                            <button
                              className="admin-danger"
                              onClick={handleArchiveSegment}
                              disabled={!canWrite || publishingSegment}
                            >
                              Архивировать
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </>
                )}
              </>
            )}

            {contentTab === 'geozones' && (
              <>
                <div className="admin-editor-title">
                  <div>
                    <p className="admin-kicker">
                      {showCreateGeoZone
                        ? 'НОВЫЙ ШАБЛОН'
                        : selectedGeoZone() ? selectedGeoZone()!.id : '—'}
                    </p>
                    <h3>
                      {showCreateGeoZone
                        ? 'Создание шаблона зоны'
                        : selectedGeoZone() ? 'Редактирование шаблона' : 'Редактор шаблона зоны'}
                    </h3>
                  </div>
                  {selectedGeoZone() && !showCreateGeoZone && (
                    <span className={`admin-status admin-status-${selectedGeoZone()!.status}`}>
                      {selectedGeoZone()!.status}
                    </span>
                  )}
                </div>

                {geoZoneError && <p className="admin-alert admin-error">{geoZoneError}</p>}
                {geoZoneNotice && <p className="admin-alert">{geoZoneNotice}</p>}

                {!showCreateGeoZone && selectedGeoZone() === null ? (
                  <p className="admin-muted">
                    Выберите шаблон слева или создайте новый.
                    Координаты генерирует сервер в момент взятия миссии.
                  </p>
                ) : (
                  <>
                    <p className="admin-muted">
                      Координаты места генерирует сервер при взятии миссии игроком:
                      в радиусе поиска от фактической точки игрока появляется зона
                      заданного размера.
                    </p>

                    <div className="admin-grid">
                      <label className="admin-span-2">
                        Название *
                        <input
                          value={geoZoneTitle}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneTitle(e.target.value)}
                        />
                      </label>

                      <label>
                        Slug *
                        <input
                          value={geoZoneSlug}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneSlug(e.target.value)}
                        />
                      </label>

                      <label>
                        Порядок сортировки
                        <input
                          type="number"
                          value={geoZoneSortOrder}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneSortOrder(e.target.value)}
                        />
                      </label>

                      <label className="admin-span-2">
                        Описание
                        <textarea
                          value={geoZoneDescription}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneDescription(e.target.value)}
                        />
                      </label>
                    </div>
                    <div className="admin-grid">
                      <label>
                        Радиус поиска * (метры)
                        <input
                          type="number"
                          value={geoZoneSearchRadiusMeters}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneSearchRadiusMeters(e.target.value)}
                        />
                        <small className="admin-muted">
                          Игрок видит этот радиус как область на карте
                        </small>
                      </label>

                      <label>
                        Размер зоны * (метры)
                        <input
                          type="number"
                          value={geoZoneRadiusMeters}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneRadiusMeters(e.target.value)}
                        />
                        <small className="admin-muted">
                          Игрок не видит размер до момента поиска
                        </small>
                      </label>

                      <label>
                        Точность GPS (метры)
                        <input
                          type="number"
                          value={geoZoneMaxAccuracy}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneMaxAccuracy(e.target.value)}
                        />
                        <small className="admin-muted">
                          Пусто — без ограничений
                        </small>
                      </label>

                      <label>
                        Время присутствия (секунды)
                        <input
                          type="number"
                          value={geoZoneMinPresence}
                          disabled={!canWrite}
                          onChange={(e) => setGeoZoneMinPresence(e.target.value)}
                        />
                      </label>
                    </div>

                    <div className="admin-grid">
                      <fieldset className="admin-span-2">
                        <legend>Ограничения размещения</legend>
                        <small className="admin-muted">
                          Сервер учтёт при генерации места зоны (реализация — Спринт 8.2)
                        </small>
                        <label>
                          <input
                            type="checkbox"
                            checked={geoZoneAvoidBuildings}
                            disabled={!canWrite}
                            onChange={(e) => setGeoZoneAvoidBuildings(e.target.checked)}
                          />
                          Избегать зданий
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={geoZoneAvoidWater}
                            disabled={!canWrite}
                            onChange={(e) => setGeoZoneAvoidWater(e.target.checked)}
                          />
                          Избегать водоёмов
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={geoZoneAvoidRoads}
                            disabled={!canWrite}
                            onChange={(e) => setGeoZoneAvoidRoads(e.target.checked)}
                          />
                          Избегать дорог
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={geoZoneAvoidPrivate}
                            disabled={!canWrite}
                            onChange={(e) => setGeoZoneAvoidPrivate(e.target.checked)}
                          />
                          Избегать частных территорий
                        </label>
                      </fieldset>
                    </div>

                    {!showCreateGeoZone && (
                      <div className="admin-grid">
                        <label>
                          Статус
                          <select
                            value={geoZoneStatus}
                            disabled={!canWrite}
                            onChange={(e) => setGeoZoneStatus(e.target.value)}
                          >
                            <option value="draft">draft — черновик</option>
                            <option value="published">published — активен</option>
                            <option value="archived">archived — архив</option>
                          </select>
                        </label>
                      </div>
                    )}

                    <div className="admin-actions">
                      {showCreateGeoZone ? (
                        <>
                          <button
                            className="admin-primary"
                            onClick={handleCreateGeoZone}
                            disabled={!canWrite || savingGeoZone}
                          >
                            {savingGeoZone ? 'Создание…' : 'Создать'}
                          </button>
                          <button
                            className="admin-secondary"
                            onClick={() => setShowCreateGeoZone(false)}
                            disabled={savingGeoZone}
                          >
                            Отмена
                          </button>
                        </>
                      ) : (
                        <button
                          className="admin-primary"
                          onClick={handleSaveGeoZone}
                          disabled={!canWrite || savingGeoZone}
                        >
                          {savingGeoZone ? 'Сохранение…' : 'Сохранить'}
                        </button>
                      )}
                    </div>
                  </>
                )}
              </>
            )}

            {contentTab === 'arobjects' && (
              <>
                <div className="admin-editor-title">
                  <div>
                    <p className="admin-kicker">
                      {showCreateARObject
                        ? 'НОВЫЙ AR-ОБЪЕКТ'
                        : selectedARObject() ? selectedARObject()!.id : '—'}
                    </p>
                    <h3>
                      {showCreateARObject
                        ? 'Создание AR-объекта'
                        : selectedARObject() ? 'Редактирование AR-объекта' : 'Редактор AR-объекта'}
                    </h3>
                  </div>
                  {selectedARObject() && !showCreateARObject && (
                    <span className={`admin-status admin-status-${selectedARObject()!.status}`}>
                      {selectedARObject()!.status}
                    </span>
                  )}
                </div>

                {arObjectError && <p className="admin-alert admin-error">{arObjectError}</p>}
                {arObjectNotice && <p className="admin-alert">{arObjectNotice}</p>}

                {!showCreateARObject && selectedARObject() === null ? (
                  <p className="admin-muted">Выберите AR-объект слева или создайте новый.</p>
                ) : (
                  <>
                    <div className="admin-grid">
                      <label className="admin-span-2">
                        Название *
                        <input value={arObjectTitle} disabled={!canWrite}
                          onChange={(e) => setARObjectTitle(e.target.value)} />
                      </label>

                      <label>
                        Slug *
                        <input value={arObjectSlug} disabled={!canWrite}
                          onChange={(e) => setARObjectSlug(e.target.value)} />
                      </label>

                      <label>
                        Порядок сортировки
                        <input type="number" value={arObjectSortOrder} disabled={!canWrite}
                          onChange={(e) => setARObjectSortOrder(e.target.value)} />
                      </label>

                      <label className="admin-span-2">
                        Описание
                        <textarea value={arObjectDescription} disabled={!canWrite}
                          onChange={(e) => setARObjectDescription(e.target.value)} />
                      </label>
                    </div>

                    <div className="admin-grid">
                      <label className="admin-span-2">
                        Геозона *
                        <select
                          value={arObjectGeoZoneId}
                          disabled={!canWrite || loadingGeoZones}
                          onChange={(e) => setARObjectGeoZoneId(e.target.value)}
                        >
                          <option value="">
                            {loadingGeoZones ? 'Загрузка…' : '— выберите зону —'}
                          </option>
                          {arObjectGeoZoneId && !geoZones.some((z) => z.id === arObjectGeoZoneId) && (
                            <option value={arObjectGeoZoneId}>
                              (нет в списке: {arObjectGeoZoneId})
                            </option>
                          )}
                          {geoZones.map((z) => (
                            <option key={z.id} value={z.id}>
                              {z.title} · {z.slug} [{z.status}]
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="admin-grid">
                      <label>
                        Тип объекта *
                        <select value={arObjectObjectType} disabled={!canWrite}
                          onChange={(e) => setARObjectObjectType(e.target.value)}>
                          <option value="cube">cube — куб</option>
                          <option value="sphere">sphere — сфера</option>
                          <option value="custom">custom — другая 3D-модель</option>
                        </select>
                      </label>

                      <label>
                        URL ассета *
                        <input value={arObjectAssetUri} disabled={!canWrite}
                          placeholder="https://cdn.example.com/models/cube.glb"
                          onChange={(e) => setARObjectAssetUri(e.target.value)} />
                      </label>

                      <label>
                        MIME-тип (опционально)
                        <input value={arObjectAssetMimeType} disabled={!canWrite}
                          placeholder="model/gltf-binary"
                          onChange={(e) => setARObjectAssetMimeType(e.target.value)} />
                      </label>

                      <label>
                        Scene preset (опционально)
                        <input value={arObjectScenePreset} disabled={!canWrite}
                          placeholder="archive_cube_damaged_v1"
                          onChange={(e) => setARObjectScenePreset(e.target.value)} />
                      </label>
                    </div>

                    <div className="admin-grid">
                      <label>
                        Размер (метры) *
                        <input type="number" step="0.1" value={arObjectScaleMeters} disabled={!canWrite}
                          onChange={(e) => setARObjectScaleMeters(e.target.value)} />
                        <small className="admin-muted">
                          Реальный размер объекта в мире. 1.0 = 1 метр.
                        </small>
                      </label>

                      <label>
                        Ориентация
                        <select value={arObjectOrientation} disabled={!canWrite}
                          onChange={(e) => setARObjectOrientation(e.target.value)}>
                          <option value="free">free — вращается</option>
                          <option value="upright">upright — стоит</option>
                          <option value="flat">flat — лежит плашмя</option>
                        </select>
                      </label>
                    </div>

                    <label className="admin-span-2">
                      Инструкция игроку (опционально)
                      <textarea value={arObjectInstructionText} disabled={!canWrite}
                        onChange={(e) => setARObjectInstructionText(e.target.value)} />
                    </label>

                    {!showCreateARObject && (
                      <div className="admin-grid">
                        <label>
                          Статус
                          <select value={arObjectStatus} disabled={!canWrite}
                            onChange={(e) => setARObjectStatus(e.target.value)}>
                            <option value="draft">draft — черновик</option>
                            <option value="published">published — активен</option>
                            <option value="archived">archived — архив</option>
                          </select>
                        </label>
                      </div>
                    )}

                    <div className="admin-actions">
                      {showCreateARObject ? (
                        <>
                          <button className="admin-primary" onClick={handleCreateARObject}
                            disabled={!canWrite || savingARObject}>
                            {savingARObject ? 'Создание…' : 'Создать'}
                          </button>
                          <button className="admin-secondary" onClick={() => setShowCreateARObject(false)}
                            disabled={savingARObject}>
                            Отмена
                          </button>
                        </>
                      ) : (
                        <button className="admin-primary" onClick={handleSaveARObject}
                          disabled={!canWrite || savingARObject}>
                          {savingARObject ? 'Сохранение…' : 'Сохранить'}
                        </button>
                      )}
                    </div>
                  </>
                )}
              </>
            )}
          </section>
        </div>
      )}

    </main>
  )
}

export default AdminApp
