import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import enUS from './locales/en-US.json'
import zhCN from './locales/zh-CN.json'

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

const DEFAULT_LOCALE: Locale = 'zh-CN'
const LOCALE_STORAGE_KEY = 'study-ai.locale'
const MESSAGES: Record<Locale, Record<string, string>> = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

type I18nParams = Record<string, string | number>

type I18nContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: I18nParams) => string
  routeLabel: (routeId: string, fallback: string) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function formatMessage(template: string, params?: I18nParams): string {
  if (!params) return template
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => {
    const value = params[key]
    return value === undefined ? match : String(value)
  })
}

export function normalizeLocale(value: unknown): Locale | '' {
  const raw = String(value || '').trim().toLowerCase().replace('_', '-')
  if (!raw) return ''
  if (raw === 'zh' || raw === 'zh-cn' || raw.startsWith('zh-hans')) return 'zh-CN'
  if (raw === 'en' || raw === 'en-us' || raw.startsWith('en-')) return 'en-US'
  return ''
}

export function resolveLocalePreference(value?: unknown): Locale {
  const explicit = normalizeLocale(value)
  if (explicit) return explicit

  if (typeof window !== 'undefined') {
    const stored = normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
    if (stored) return stored
  }

  if (typeof navigator !== 'undefined') {
    const languages = navigator.languages?.length ? navigator.languages : [navigator.language]
    for (const language of languages) {
      const locale = normalizeLocale(language)
      if (locale) return locale
    }
  }

  return DEFAULT_LOCALE
}

export function createTranslator(locale: Locale) {
  return (key: string, params?: I18nParams): string => {
    const table = MESSAGES[locale] || MESSAGES[DEFAULT_LOCALE]
    const fallbackTable = MESSAGES[DEFAULT_LOCALE]
    return formatMessage(table[key] || fallbackTable[key] || key, params)
  }
}

function setDocumentLocale(locale: Locale): void {
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => resolveLocalePreference())

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(resolveLocalePreference(nextLocale))
  }, [])

  useEffect(() => {
    setDocumentLocale(locale)
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  }, [locale])

  const t = useMemo(() => createTranslator(locale), [locale])

  const routeLabel = useCallback(
    (routeId: string, fallback: string) => {
      const key = `route.${routeId}`
      const label = t(key)
      return label === key ? fallback : label
    },
    [t],
  )

  const value = useMemo<I18nContextValue>(() => ({ locale, setLocale, t, routeLabel }), [locale, routeLabel, setLocale, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext)
  if (!value) {
    throw new Error('useI18n must be used within I18nProvider')
  }
  return value
}
