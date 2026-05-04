export const BREAKPOINTS = {
  lg: 1024,
} as const

export const MEDIA_QUERIES = {
  mobile: `(max-width: ${BREAKPOINTS.lg - 1}px)`,
} as const
