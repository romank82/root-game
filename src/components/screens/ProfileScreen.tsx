import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  createGasInvoice,
  getEngineBootstrap,
  getMyProfile,
  saveMyProfile,
  sendGasInvoice,
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
// Полный официальный список ISO 3166-1 alpha-2 (249 стран и территорий)
// с русскими названиями (источник: CLDR ru). Сначала — самые частые страны,
// дальше — в алфавитном порядке (по русскому названию).
const COUNTRY_OPTIONS: { value: string; label: string }[] = [
  { value: 'RU', label: 'Россия' },
  { value: 'KZ', label: 'Казахстан' },
  { value: 'BY', label: 'Беларусь' },
  { value: 'UA', label: 'Украина' },
  { value: 'US', label: 'США' },
  { value: 'DE', label: 'Германия' },
  { value: 'FR', label: 'Франция' },
  { value: 'GB', label: 'Великобритания' },
  { value: 'TR', label: 'Турция' },
  { value: 'AE', label: 'ОАЭ' },
  { value: 'AU', label: 'Австралия' },
  { value: 'AT', label: 'Австрия' },
  { value: 'AZ', label: 'Азербайджан' },
  { value: 'AX', label: 'Аландские острова' },
  { value: 'AL', label: 'Албания' },
  { value: 'DZ', label: 'Алжир' },
  { value: 'AS', label: 'Американское Самоа' },
  { value: 'AI', label: 'Ангилья' },
  { value: 'AO', label: 'Ангола' },
  { value: 'AD', label: 'Андорра' },
  { value: 'AQ', label: 'Антарктида' },
  { value: 'AG', label: 'Антигуа и Барбуда' },
  { value: 'AR', label: 'Аргентина' },
  { value: 'AM', label: 'Армения' },
  { value: 'AW', label: 'Аруба' },
  { value: 'AF', label: 'Афганистан' },
  { value: 'BS', label: 'Багамы' },
  { value: 'BD', label: 'Бангладеш' },
  { value: 'BB', label: 'Барбадос' },
  { value: 'BH', label: 'Бахрейн' },
  { value: 'BZ', label: 'Белиз' },
  { value: 'BE', label: 'Бельгия' },
  { value: 'BJ', label: 'Бенин' },
  { value: 'BM', label: 'Бермудские острова' },
  { value: 'BG', label: 'Болгария' },
  { value: 'BO', label: 'Боливия' },
  { value: 'BQ', label: 'Бонэйр, Синт-Эстатиус и Саба' },
  { value: 'BA', label: 'Босния и Герцеговина' },
  { value: 'BW', label: 'Ботсвана' },
  { value: 'BR', label: 'Бразилия' },
  { value: 'IO', label: 'Британская территория в Индийском океане' },
  { value: 'BN', label: 'Бруней' },
  { value: 'BF', label: 'Буркина-Фасо' },
  { value: 'BI', label: 'Бурунди' },
  { value: 'BT', label: 'Бутан' },
  { value: 'VU', label: 'Вануату' },
  { value: 'VA', label: 'Ватикан' },
  { value: 'HU', label: 'Венгрия' },
  { value: 'VE', label: 'Венесуэла' },
  { value: 'VG', label: 'Виргинские острова (Великобритания)' },
  { value: 'VI', label: 'Виргинские острова (США)' },
  { value: 'UM', label: 'Внешние малые острова (США)' },
  { value: 'TL', label: 'Восточный Тимор' },
  { value: 'VN', label: 'Вьетнам' },
  { value: 'GA', label: 'Габон' },
  { value: 'HT', label: 'Гаити' },
  { value: 'GY', label: 'Гайана' },
  { value: 'GM', label: 'Гамбия' },
  { value: 'GH', label: 'Гана' },
  { value: 'GP', label: 'Гваделупа' },
  { value: 'GT', label: 'Гватемала' },
  { value: 'GN', label: 'Гвинея' },
  { value: 'GW', label: 'Гвинея-Бисау' },
  { value: 'GG', label: 'Гернси' },
  { value: 'GI', label: 'Гибралтар' },
  { value: 'HN', label: 'Гондурас' },
  { value: 'HK', label: 'Гонконг' },
  { value: 'GD', label: 'Гренада' },
  { value: 'GL', label: 'Гренландия' },
  { value: 'GR', label: 'Греция' },
  { value: 'GE', label: 'Грузия' },
  { value: 'GU', label: 'Гуам' },
  { value: 'DK', label: 'Дания' },
  { value: 'JE', label: 'Джерси' },
  { value: 'DJ', label: 'Джибути' },
  { value: 'DM', label: 'Доминика' },
  { value: 'DO', label: 'Доминиканская Республика' },
  { value: 'EG', label: 'Египет' },
  { value: 'ZM', label: 'Замбия' },
  { value: 'EH', label: 'Западная Сахара' },
  { value: 'ZW', label: 'Зимбабве' },
  { value: 'IL', label: 'Израиль' },
  { value: 'IN', label: 'Индия' },
  { value: 'ID', label: 'Индонезия' },
  { value: 'JO', label: 'Иордания' },
  { value: 'IQ', label: 'Ирак' },
  { value: 'IR', label: 'Иран' },
  { value: 'IE', label: 'Ирландия' },
  { value: 'IS', label: 'Исландия' },
  { value: 'ES', label: 'Испания' },
  { value: 'IT', label: 'Италия' },
  { value: 'YE', label: 'Йемен' },
  { value: 'CV', label: 'Кабо-Верде' },
  { value: 'KH', label: 'Камбоджа' },
  { value: 'CM', label: 'Камерун' },
  { value: 'CA', label: 'Канада' },
  { value: 'QA', label: 'Катар' },
  { value: 'KE', label: 'Кения' },
  { value: 'CY', label: 'Кипр' },
  { value: 'KG', label: 'Киргизия' },
  { value: 'KI', label: 'Кирибати' },
  { value: 'CN', label: 'Китай' },
  { value: 'KP', label: 'КНДР' },
  { value: 'CC', label: 'Кокосовые острова' },
  { value: 'CO', label: 'Колумбия' },
  { value: 'KM', label: 'Коморы' },
  { value: 'CG', label: 'Конго - Браззавиль' },
  { value: 'CD', label: 'Конго - Киншаса' },
  { value: 'CR', label: 'Коста-Рика' },
  { value: 'CI', label: 'Кот-д’Ивуар' },
  { value: 'CU', label: 'Куба' },
  { value: 'KW', label: 'Кувейт' },
  { value: 'CW', label: 'Кюрасао' },
  { value: 'LA', label: 'Лаос' },
  { value: 'LV', label: 'Латвия' },
  { value: 'LS', label: 'Лесото' },
  { value: 'LR', label: 'Либерия' },
  { value: 'LB', label: 'Ливан' },
  { value: 'LY', label: 'Ливия' },
  { value: 'LT', label: 'Литва' },
  { value: 'LI', label: 'Лихтенштейн' },
  { value: 'LU', label: 'Люксембург' },
  { value: 'MU', label: 'Маврикий' },
  { value: 'MR', label: 'Мавритания' },
  { value: 'MG', label: 'Мадагаскар' },
  { value: 'YT', label: 'Майотта' },
  { value: 'MO', label: 'Макао' },
  { value: 'MW', label: 'Малави' },
  { value: 'MY', label: 'Малайзия' },
  { value: 'ML', label: 'Мали' },
  { value: 'MV', label: 'Мальдивы' },
  { value: 'MT', label: 'Мальта' },
  { value: 'MA', label: 'Марокко' },
  { value: 'MQ', label: 'Мартиника' },
  { value: 'MH', label: 'Маршалловы острова' },
  { value: 'MX', label: 'Мексика' },
  { value: 'MZ', label: 'Мозамбик' },
  { value: 'MD', label: 'Молдова' },
  { value: 'MC', label: 'Монако' },
  { value: 'MN', label: 'Монголия' },
  { value: 'MS', label: 'Монтсеррат' },
  { value: 'MM', label: 'Мьянма' },
  { value: 'NA', label: 'Намибия' },
  { value: 'NR', label: 'Науру' },
  { value: 'NP', label: 'Непал' },
  { value: 'NE', label: 'Нигер' },
  { value: 'NG', label: 'Нигерия' },
  { value: 'NL', label: 'Нидерланды' },
  { value: 'NI', label: 'Никарагуа' },
  { value: 'NU', label: 'Ниуэ' },
  { value: 'NZ', label: 'Новая Зеландия' },
  { value: 'NC', label: 'Новая Каледония' },
  { value: 'NO', label: 'Норвегия' },
  { value: 'OM', label: 'Оман' },
  { value: 'BV', label: 'Остров Буве' },
  { value: 'IM', label: 'Остров Мэн' },
  { value: 'NF', label: 'Остров Норфолк' },
  { value: 'CX', label: 'Остров Рождества' },
  { value: 'SH', label: 'Остров Св. Елены' },
  { value: 'KY', label: 'Острова Кайман' },
  { value: 'CK', label: 'Острова Кука' },
  { value: 'PN', label: 'Острова Питкэрн' },
  { value: 'HM', label: 'Острова Херд и Макдональд' },
  { value: 'PK', label: 'Пакистан' },
  { value: 'PW', label: 'Палау' },
  { value: 'PS', label: 'Палестинские территории' },
  { value: 'PA', label: 'Панама' },
  { value: 'PG', label: 'Папуа — Новая Гвинея' },
  { value: 'PY', label: 'Парагвай' },
  { value: 'PE', label: 'Перу' },
  { value: 'PL', label: 'Польша' },
  { value: 'PT', label: 'Португалия' },
  { value: 'PR', label: 'Пуэрто-Рико' },
  { value: 'RE', label: 'Реюньон' },
  { value: 'RW', label: 'Руанда' },
  { value: 'RO', label: 'Румыния' },
  { value: 'SV', label: 'Сальвадор' },
  { value: 'WS', label: 'Самоа' },
  { value: 'SM', label: 'Сан-Марино' },
  { value: 'ST', label: 'Сан-Томе и Принсипи' },
  { value: 'SA', label: 'Саудовская Аравия' },
  { value: 'MK', label: 'Северная Македония' },
  { value: 'MP', label: 'Северные Марианские острова' },
  { value: 'SC', label: 'Сейшельские острова' },
  { value: 'BL', label: 'Сен-Бартелеми' },
  { value: 'MF', label: 'Сен-Мартен' },
  { value: 'PM', label: 'Сен-Пьер и Микелон' },
  { value: 'SN', label: 'Сенегал' },
  { value: 'VC', label: 'Сент-Винсент и Гренадины' },
  { value: 'KN', label: 'Сент-Китс и Невис' },
  { value: 'LC', label: 'Сент-Люсия' },
  { value: 'RS', label: 'Сербия' },
  { value: 'SG', label: 'Сингапур' },
  { value: 'SX', label: 'Синт-Мартен' },
  { value: 'SY', label: 'Сирия' },
  { value: 'SK', label: 'Словакия' },
  { value: 'SI', label: 'Словения' },
  { value: 'SB', label: 'Соломоновы острова' },
  { value: 'SO', label: 'Сомали' },
  { value: 'SD', label: 'Судан' },
  { value: 'SR', label: 'Суринам' },
  { value: 'SL', label: 'Сьерра-Леоне' },
  { value: 'TJ', label: 'Таджикистан' },
  { value: 'TH', label: 'Таиланд' },
  { value: 'TW', label: 'Тайвань' },
  { value: 'TZ', label: 'Танзания' },
  { value: 'TG', label: 'Того' },
  { value: 'TK', label: 'Токелау' },
  { value: 'TO', label: 'Тонга' },
  { value: 'TT', label: 'Тринидад и Тобаго' },
  { value: 'TV', label: 'Тувалу' },
  { value: 'TN', label: 'Тунис' },
  { value: 'TM', label: 'Туркменистан' },
  { value: 'TC', label: 'Тёркс и Кайкос' },
  { value: 'UG', label: 'Уганда' },
  { value: 'UZ', label: 'Узбекистан' },
  { value: 'WF', label: 'Уоллис и Футуна' },
  { value: 'UY', label: 'Уругвай' },
  { value: 'FO', label: 'Фарерские острова' },
  { value: 'FM', label: 'Федеративные Штаты Микронезии' },
  { value: 'FJ', label: 'Фиджи' },
  { value: 'PH', label: 'Филиппины' },
  { value: 'FI', label: 'Финляндия' },
  { value: 'FK', label: 'Фолклендские острова' },
  { value: 'GF', label: 'Французская Гвиана' },
  { value: 'PF', label: 'Французская Полинезия' },
  { value: 'TF', label: 'Французские Южные территории' },
  { value: 'HR', label: 'Хорватия' },
  { value: 'CF', label: 'Центрально-Африканская Республика' },
  { value: 'TD', label: 'Чад' },
  { value: 'ME', label: 'Черногория' },
  { value: 'CZ', label: 'Чехия' },
  { value: 'CL', label: 'Чили' },
  { value: 'CH', label: 'Швейцария' },
  { value: 'SE', label: 'Швеция' },
  { value: 'SJ', label: 'Шпицберген и Ян-Майен' },
  { value: 'LK', label: 'Шри-Ланка' },
  { value: 'EC', label: 'Эквадор' },
  { value: 'GQ', label: 'Экваториальная Гвинея' },
  { value: 'ER', label: 'Эритрея' },
  { value: 'SZ', label: 'Эсватини' },
  { value: 'EE', label: 'Эстония' },
  { value: 'ET', label: 'Эфиопия' },
  { value: 'GS', label: 'Южная Георгия и Южные Сандвичевы острова' },
  { value: 'KR', label: 'Южная Корея' },
  { value: 'ZA', label: 'Южно-Африканская Республика' },
  { value: 'SS', label: 'Южный Судан' },
  { value: 'JM', label: 'Ямайка' },
  { value: 'JP', label: 'Япония' },
]

// 10.4-j-1: пакеты газа. Цены соответствуют CMS-каталогу gas packs
// (economy.*); подпись кнопки — «объём (цена в Stars)».
const GAS_PACKS: { amount: number; label: string }[] = [
  { amount: 10, label: '10 газа (10 ⭐)' },
  { amount: 100, label: '100 газа (80 ⭐)' },
  { amount: 1000, label: '1000 газа (700 ⭐)' },
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
// При countryLocked (source='auto') country в payload НЕ попадает вовсе:
// бэк на ручную смену страны отвечает 422 — шлём только gender/age.
function buildPayload(
  draft: DraftState,
  countryLocked: boolean,
): MyProfilePayload {
  const payload: MyProfilePayload = {
    gender: draft.gender === '' ? null : draft.gender,
    age: draft.age === '' ? null : Number(draft.age),
  }
  if (!countryLocked) {
    const country = draft.country.trim().toUpperCase()
    payload.country = country === '' ? null : country
  }
  return payload
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
  // 10.4-j-1: газ — баланс (из bootstrap), состояние покупки и уведомления.
  const [gasBalance, setGasBalance] = useState<string | null>(null)
  const [buyingGas, setBuyingGas] = useState(false)
  const [gasError, setGasError] = useState<string | null>(null)
  const [gasNotice, setGasNotice] = useState<string | null>(null)
  // 10.0.5-b-2: страна определена автоматически по координатам ('auto') —
  // select disabled, hint под ним, country не попадает в payload.
  const countryLocked = profile?.country_source === 'auto'

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

  // 10.4-j-1: свежий баланс газа на момент открытия профиля.
  useEffect(() => {
    let cancelled = false
    getEngineBootstrap()
      .then((data) => {
        if (cancelled) return
        setGasBalance(data.gasBalance)
      })
      .catch(() => {
        // Газ — доп. информация: при сбое bootstrap блок остаётся «—»,
        // анкета (основной контент экрана) не ломается.
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Черновик изменён, если нормализованные значения отличаются от
  // сохранённого профиля (для age пустая строка и null эквивалентны).
  function isDirty(): boolean {
    if (profile === null) return false
    const next = buildPayload(draft, countryLocked)
    return (
      // При countryLocked select disabled — страна изменением не считается.
      (!countryLocked && (next.country ?? '') !== (profile.country ?? '')) ||
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
      const result = await saveMyProfile(buildPayload(draft, countryLocked))
      setProfile(result.player)
      setDraft(draftFromPlayer(result.player))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  // 10.4-j-1: покупка газа через Stars-инвойс. Ссылку создаёт бэк
  // (createGasInvoice); оплата открывается штатным Telegram WebApp
  // (openInvoice). Реальный зачёт газа делает backend по статусу платежа —
  // фронт после 'paid' перечитывает bootstrap, чтобы показать новый баланс.
  async function handleBuyGas(gasAmount: number) {
    if (buyingGas) return
    setBuyingGas(true)
    setGasError(null)
    setGasNotice(null)
    // 10.4-fix-b: на Android WebView openInvoice не доставляет
    // pre_checkout_query (известный баг Telegram) — отправляем инвойс в чат
    // с ботом (sendInvoice) и показываем подсказку. Имя бота фронту WebApp
    // не отдаёт (telegram.d.ts его не типизирует), поэтому openTelegramLink
    // не строим — только подсказка. На остальных платформах — как раньше.
    const webApp = window.Telegram?.WebApp as
      | { platform?: string }
      | undefined
    const platform = webApp?.platform
    if (platform === 'android' || platform === 'android_x') {
      try {
        await sendGasInvoice(gasAmount)
        setGasNotice(
          'Инвойс отправлен в чат с ботом. Откройте чат с ботом и оплатите.',
        )
      } catch (err) {
        setGasError((err as Error).message)
      } finally {
        setBuyingGas(false)
      }
      return
    }
    try {
      const invoice = await createGasInvoice(gasAmount)
      // telegram.d.ts не описывает openInvoice (WebApp типизирован частично),
      // поэтому сужаем тип локально; метод опционален.
      const webAppWithInvoice = window.Telegram?.WebApp as
        | {
            openInvoice?: (
              url: string,
              callback: (status: string) => void,
            ) => void
          }
        | undefined
      if (webAppWithInvoice?.openInvoice) {
        webAppWithInvoice.openInvoice(invoice.invoiceLink, (status) => {
          if (status === 'paid') {
            getEngineBootstrap()
              .then((data) => {
                setGasBalance(data.gasBalance)
                setGasNotice('Газ зачислен (после подтверждения).')
              })
              .catch((err: Error) => {
                setGasError(err.message)
              })
          } else {
            setGasError(`Оплата не завершена: ${status}.`)
          }
        })
      } else {
        // Fallback вне Telegram WebApp: открыть ссылку инвойса в новой
        // вкладке (в WebView openInvoice обычно присутствует).
        window.open(invoice.invoiceLink, '_blank')
        setGasNotice('Инвойс открыт в новой вкладке (вне Telegram WebApp).')
      }
    } catch (err) {
      setGasError((err as Error).message)
    } finally {
      setBuyingGas(false)
    }
  }

  return (
    <section className="inventory">
      <p className="eyebrow">ПРОФИЛЬ / АНКЕТА ИГРОКА</p>
      <h2>Профиль</h2>

      <div className="gas-block">
        <h3>Газ</h3>
        <p>
          Баланс: <b>{gasBalance ?? '—'}</b>
        </p>
        {gasError && <p className="repair-error">{gasError}</p>}
        {gasNotice && <p className="mission-success-card">{gasNotice}</p>}
        {GAS_PACKS.map((pack) => (
          <button
            key={pack.amount}
            type="button"
            className="primary-button"
            disabled={buyingGas}
            onClick={() => handleBuyGas(pack.amount)}
          >
            {pack.label}
          </button>
        ))}
        {buyingGas && <p>Создаём инвойс…</p>}
      </div>

      {loading && <p>Загрузка…</p>}
      {error && <p className="repair-error">{error}</p>}

      {!loading && profile && (
        <>
          <p>
            Игрок: <b>{profile.nickname}</b>
          </p>

          <label>
            Страна
            <select
              value={draft.country}
              disabled={countryLocked}
              onChange={(e) => setDraft({ ...draft, country: e.target.value })}
            >
              <option value="">Не указана</option>
              {COUNTRY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {countryLocked && (
              <small>
                Страна определена автоматически по координатам и не может
                быть изменена в анкете.
              </small>
            )}
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