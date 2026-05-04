import { useEffect } from 'react'
import { APP_BRAND_NAME } from '@/constants/branding'

export function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} - ${APP_BRAND_NAME}` : APP_BRAND_NAME
  }, [title])
}
