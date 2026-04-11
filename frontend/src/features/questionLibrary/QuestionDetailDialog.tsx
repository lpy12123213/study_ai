import { Dialog, DialogContent } from '@/components/ui/dialog'
import { QuestionDetailPane } from '@/features/questionLibrary/QuestionDetailPane'
import type { QuestionLibraryDetailResponse, QuestionLibraryListItem } from '@/api/questionLibrary'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedId: string
  listItem: QuestionLibraryListItem | null
  detail: QuestionLibraryDetailResponse | null
  isLoading: boolean
  error: any
  onMutated: () => void
}

export function QuestionDetailDialog(props: Props) {
  const { open, onOpenChange, selectedId, listItem, detail, isLoading, error, onMutated } = props

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[920px] h-[82vh] p-0 overflow-hidden">
        <QuestionDetailPane
          selectedId={selectedId}
          listItem={listItem}
          detail={detail}
          isLoading={isLoading}
          error={error}
          onMutated={onMutated}
        />
      </DialogContent>
    </Dialog>
  )
}

