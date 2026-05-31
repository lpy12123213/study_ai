/**
 * Re-export of the canonical {@link TagEditDialog} from `@/components/shared`.
 *
 * The original implementation lived here; it has been promoted to the shared
 * components folder so master-detail pages (Papers, StudyArchives, ...) can
 * reuse it instead of falling back to ad-hoc `window.prompt` dialogs.
 *
 * Existing imports under `historySidebar` keep working through this thin
 * forwarder. Prefer importing from `@/components/shared/TagEditDialog` in new
 * code.
 */
export { TagEditDialog } from '@/components/shared/TagEditDialog'
