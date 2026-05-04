import { useEffect, useState } from 'react'

function getMatches(query: string, defaultValue: boolean) {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return defaultValue
  }
  return window.matchMedia(query).matches
}

export function useMediaQuery(query: string, defaultValue = false) {
  const [matches, setMatches] = useState(() => getMatches(query, defaultValue))

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }

    const media = window.matchMedia(query)
    const update = (event?: MediaQueryListEvent) => {
      setMatches(event ? event.matches : media.matches)
    }

    update()
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update)
      return () => media.removeEventListener('change', update)
    }

    media.addListener(update)
    return () => media.removeListener(update)
  }, [query])

  return matches
}
