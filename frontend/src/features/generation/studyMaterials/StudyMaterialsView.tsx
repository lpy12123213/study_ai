import { LatexExportDialog } from '@/features/generation/studyMaterials/components/LatexExportDialog'
import { StudyMaterialsComposer } from '@/features/generation/studyMaterials/components/StudyMaterialsComposer'
import { StudyMaterialsWorkspace } from '@/features/generation/studyMaterials/components/StudyMaterialsWorkspace'
import { WelcomeScreen } from '@/features/generation/studyMaterials/components/WelcomeScreen'
import { useStudyMaterialsController } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsController'

export default function StudyMaterialsPage() {
  const controller = useStudyMaterialsController()
  const showWelcome = controller.messages.length === 0 && !controller.hasSubAgentPane

  return (
    <div ref={controller.containerRef} className="aurora-materials-screen h-full flex flex-col relative overflow-hidden min-h-0">
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

