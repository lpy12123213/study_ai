import { useAppearanceStore } from '@/stores/useAppearanceStore'

export function useLayoutPrefs() {
  const sidebarStyle = useAppearanceStore((state) => state.sidebarStyle)
  const sidebarCollapsed = useAppearanceStore((state) => state.sidebarCollapsed)
  const sidebarPosition = useAppearanceStore((state) => state.sidebarPosition)
  const contentLayout = useAppearanceStore((state) => state.contentLayout)
  const setSidebarCollapsed = useAppearanceStore((state) => state.setSidebarCollapsed)

  return {
    sidebarStyle,
    sidebarCollapsed,
    sidebarPosition,
    contentLayout,
    setSidebarCollapsed,
  }
}
