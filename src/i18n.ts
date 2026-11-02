import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
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
  },
}

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: 'ru',
    fallbackLng: 'ru',
    defaultNS: 'common',
    ns: ['common', 'errors', 'terminal', 'profile', 'shop', 'team', 'scanner', 'cipher', 'archive', 'map', 'inventory', 'transfer'],
    interpolation: { escapeValue: false },
  })

export default i18n
