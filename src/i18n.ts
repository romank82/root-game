import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import ruCommon from './locales/ru/common.json'
import ruErrors from './locales/ru/errors.json'
import ruTerminal from './locales/ru/terminal.json'
import ruProfile from './locales/ru/profile.json'
import ruShop from './locales/ru/shop.json'
import ruTeam from './locales/ru/team.json'
import ruScanner from './locales/ru/scanner.json'
import ruCipher from './locales/ru/cipher.json'
import ruArchive from './locales/ru/archive.json'
import ruMap from './locales/ru/map.json'
import ruInventory from './locales/ru/inventory.json'
import ruTransfer from './locales/ru/transfer.json'
import ruBriefing from './locales/ru/briefing.json'
import ruMemory from './locales/ru/memory.json'
import enCommon from './locales/en/common.json'
import enErrors from './locales/en/errors.json'
import enTerminal from './locales/en/terminal.json'
import enProfile from './locales/en/profile.json'
import enShop from './locales/en/shop.json'
import enTeam from './locales/en/team.json'
import enScanner from './locales/en/scanner.json'
import enCipher from './locales/en/cipher.json'
import enArchive from './locales/en/archive.json'
import enMap from './locales/en/map.json'
import enInventory from './locales/en/inventory.json'
import enTransfer from './locales/en/transfer.json'
import enBriefing from './locales/en/briefing.json'
import enMemory from './locales/en/memory.json'
import zhCommon from './locales/zh/common.json'
import zhErrors from './locales/zh/errors.json'
import zhTerminal from './locales/zh/terminal.json'
import zhProfile from './locales/zh/profile.json'
import zhShop from './locales/zh/shop.json'
import zhTeam from './locales/zh/team.json'
import zhScanner from './locales/zh/scanner.json'
import zhCipher from './locales/zh/cipher.json'
import zhArchive from './locales/zh/archive.json'
import zhMap from './locales/zh/map.json'
import zhInventory from './locales/zh/inventory.json'
import zhTransfer from './locales/zh/transfer.json'
import zhBriefing from './locales/zh/briefing.json'
import zhMemory from './locales/zh/memory.json'

const resources = {
  ru: {
    common: ruCommon,
    errors: ruErrors,
    terminal: ruTerminal,
    profile: ruProfile,
    shop: ruShop,
    team: ruTeam,
    scanner: ruScanner,
    cipher: ruCipher,
    archive: ruArchive,
    map: ruMap,
    inventory: ruInventory,
    transfer: ruTransfer,
    briefing: ruBriefing,
    memory: ruMemory,
  },
  en: {
    common: enCommon,
    errors: enErrors,
    terminal: enTerminal,
    profile: enProfile,
    shop: enShop,
    team: enTeam,
    scanner: enScanner,
    cipher: enCipher,
    archive: enArchive,
    map: enMap,
    inventory: enInventory,
    transfer: enTransfer,
    briefing: enBriefing,
    memory: enMemory,
  },
  zh: {
    common: zhCommon,
    errors: zhErrors,
    terminal: zhTerminal,
    profile: zhProfile,
    shop: zhShop,
    team: zhTeam,
    scanner: zhScanner,
    cipher: zhCipher,
    archive: zhArchive,
    map: zhMap,
    inventory: zhInventory,
    transfer: zhTransfer,
    briefing: zhBriefing,
    memory: zhMemory,
  },
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'ru',
    supportedLngs: ['ru', 'en', 'zh'],
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
    },
    defaultNS: 'common',
    ns: ['common', 'errors', 'terminal', 'profile', 'shop', 'team', 'scanner', 'cipher', 'memory', 'map', 'inventory', 'transfer', 'briefing'],
    interpolation: { escapeValue: false },
  })

export default i18n
