import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ResumeControl } from '@/components/task/ResumeControl'
import type { ResumableTask } from '@/types'

describe('ResumeControl', () => {
  it('renders zero-step progress without NaN width', () => {
    const checkpoint: ResumableTask = {
      taskId: 'task-1',
      taskType: 'study_materials',
      status: 'paused',
      currentStep: 0,
      totalSteps: 0,
      checkpoint: {
        completedSteps: [],
        pendingSteps: [],
        context: {},
      },
      canResume: true,
    }

    const { container } = render(<ResumeControl taskId="task-1" checkpoint={checkpoint} />)
    const progressFill = Array.from(container.querySelectorAll<HTMLElement>('[style]')).find((el) =>
      String(el.getAttribute('style') || '').includes('width'),
    )

    expect(progressFill?.getAttribute('style') ?? '').toContain('width: 0%')
  })
})
