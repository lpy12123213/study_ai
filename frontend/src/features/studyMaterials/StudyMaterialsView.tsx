import { LatexExportDialog } from '@/features/studyMaterials/components/LatexExportDialog'
import { StudyMaterialsComposer } from '@/features/studyMaterials/components/StudyMaterialsComposer'
import { StudyMaterialsWorkspace } from '@/features/studyMaterials/components/StudyMaterialsWorkspace'
import { WelcomeScreen } from '@/features/studyMaterials/components/WelcomeScreen'
import { useStudyMaterialsController } from '@/features/studyMaterials/hooks/useStudyMaterialsController'

export default function StudyMaterialsPage() {
  const controller = useStudyMaterialsController()
  const showWelcome = controller.messages.length === 0 && !controller.hasSubAgentPane

  return (
    <div ref={controller.containerRef} className="h-full flex flex-col relative overflow-hidden min-h-0">
      {showWelcome ? (
        <WelcomeScreen subject={controller.subject} onExampleClick={(text) => controller.setInput(text)} />
      ) : (
        <StudyMaterialsWorkspace controller={controller} />
      )}

      <StudyMaterialsComposer controller={controller} />
      <LatexExportDialog controller={controller} />
    </div>
  )
}

