# AI 出题流式编辑器 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a new high-visual AI question generation studio page that streams question artifacts card-by-card and makes the output process transparent to the user.

**Architecture:** Replace the current single-column `AiGenerateWorkspace` with an editor-style shell composed of a mission composer, generation stream, context rail, and confirmed shelf. Reuse existing question-library task hooks and preview APIs first, then layer a local streaming artifact model on top so the UI can show question-level progress without breaking the current backend contract.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind v4, Radix UI primitives, Framer Motion, TanStack Query, existing project stores/hooks

---

### Task 1: Add the page shell and preserve route compatibility

**Files:**
- Modify: `frontend/src/pages/AiGeneratePage.tsx`
- Create: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Create: `frontend/src/pages/aiGenerate/types.ts`
- Test: `frontend/src/pages/aiGenerate/__tests__/aiGenerateStudioPage.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import AiGeneratePage from '@/pages/AiGeneratePage'

test('renders the AI generation studio shell', async () => {
  render(<AiGeneratePage />)
  expect(await screen.findByText('AI 出题工作台')).toBeInTheDocument()
  expect(screen.getByText('开始生成')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- aiGenerateStudioPage`
Expected: FAIL because the new title and shell do not exist yet.

**Step 3: Write minimal implementation**

- Create `AiGenerateStudioPage.tsx` with top-level shell regions:
  - mission bar
  - generation stream
  - context rail
  - confirmed shelf placeholder
- Keep `AiGeneratePage.tsx` as the route entry that returns the new studio page.
- Add shared TS types for session status, artifact section status, and draft card shape.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- aiGenerateStudioPage`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/AiGeneratePage.tsx frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/pages/aiGenerate/types.ts frontend/src/pages/aiGenerate/__tests__/aiGenerateStudioPage.test.tsx
git commit -m "feat(frontend): add ai generate studio shell"
```

### Task 2: Build the mission composer with prompt-first controls

**Files:**
- Create: `frontend/src/pages/aiGenerate/MissionComposer.tsx`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Test: `frontend/src/pages/aiGenerate/__tests__/missionComposer.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MissionComposer } from '@/pages/aiGenerate/MissionComposer'

test('shows advanced controls on demand', async () => {
  render(<MissionComposer {...props} />)
  await userEvent.click(screen.getByRole('button', { name: '高级控制' }))
  expect(screen.getByLabelText('学科')).toBeInTheDocument()
  expect(screen.getByLabelText('题量')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- missionComposer`
Expected: FAIL because the component does not exist.

**Step 3: Write minimal implementation**

- Implement a prompt-first composer with:
  - natural-language textarea/input
  - compact chips showing subject, difficulty, count, question type
  - `引用自学资料` toggle
  - `高级控制` expand/collapse panel
  - `开始生成` primary CTA
- Wire subject options from `useSubjects`.
- Keep prop contract purely presentational.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- missionComposer`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/aiGenerate/MissionComposer.tsx frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/pages/aiGenerate/__tests__/missionComposer.test.tsx
git commit -m "feat(frontend): add ai generate mission composer"
```

### Task 3: Introduce question draft cards with staged artifact sections

**Files:**
- Create: `frontend/src/pages/aiGenerate/QuestionDraftCard.tsx`
- Create: `frontend/src/pages/aiGenerate/ArtifactSection.tsx`
- Create: `frontend/src/pages/aiGenerate/GenerationStream.tsx`
- Modify: `frontend/src/pages/aiGenerate/types.ts`
- Test: `frontend/src/pages/aiGenerate/__tests__/questionDraftCard.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { QuestionDraftCard } from '@/pages/aiGenerate/QuestionDraftCard'

test('renders staged artifact sections', () => {
  render(<QuestionDraftCard draft={draft} />)
  expect(screen.getByText('题干')).toBeInTheDocument()
  expect(screen.getByText('答案')).toBeInTheDocument()
  expect(screen.getByText('解析')).toBeInTheDocument()
  expect(screen.getByText('题干已完成')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- questionDraftCard`
Expected: FAIL because the card components do not exist.

**Step 3: Write minimal implementation**

- Create card UI with:
  - question index + status chip
  - timestamp/status metadata
  - three artifact sections
  - edit area per section
  - local action buttons: lock, regenerate section, retry question
- Create a stream container that renders draft cards in order and handles empty/loading states.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- questionDraftCard`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/aiGenerate/QuestionDraftCard.tsx frontend/src/pages/aiGenerate/ArtifactSection.tsx frontend/src/pages/aiGenerate/GenerationStream.tsx frontend/src/pages/aiGenerate/types.ts frontend/src/pages/aiGenerate/__tests__/questionDraftCard.test.tsx
git commit -m "feat(frontend): add staged ai question draft cards"
```

### Task 4: Add a local session reducer that maps existing preview data into a stream model

**Files:**
- Create: `frontend/src/pages/aiGenerate/useAiGenerateSession.ts`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/pages/aiGenerate/types.ts`
- Test: `frontend/src/pages/aiGenerate/__tests__/useAiGenerateSession.test.ts`

**Step 1: Write the failing test**

```ts
import { reduceTaskPreviewToDrafts } from '@/pages/aiGenerate/useAiGenerateSession'

test('maps preview questions into ordered draft cards', () => {
  const result = reduceTaskPreviewToDrafts(preview)
  expect(result.drafts).toHaveLength(2)
  expect(result.drafts[0].sections.stem.status).toBe('done')
  expect(result.drafts[0].sections.answer.status).toBe('done')
  expect(result.drafts[0].sections.analysis.status).toBe('done')
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- useAiGenerateSession`
Expected: FAIL because the reducer/hook does not exist.

**Step 3: Write minimal implementation**

- Create a session hook/reducer that manages:
  - session status
  - draft cards
  - confirmed IDs
  - selected card
- Convert `tasks.draftPreview` into ordered card state.
- Add a progressive reveal mode so completed preview data can still animate section-by-section in the UI.
- Keep mutations local until explicit commit/discard.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- useAiGenerateSession`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/aiGenerate/useAiGenerateSession.ts frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/pages/aiGenerate/types.ts frontend/src/pages/aiGenerate/__tests__/useAiGenerateSession.test.ts
git commit -m "feat(frontend): add ai generate session reducer"
```

### Task 5: Build the context rail and fold existing task controls into it

**Files:**
- Create: `frontend/src/pages/aiGenerate/ContextRail.tsx`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/pages/questionLibrary/RunPanel.tsx`
- Test: `frontend/src/pages/aiGenerate/__tests__/contextRail.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { ContextRail } from '@/pages/aiGenerate/ContextRail'

test('renders task summary and global controls', () => {
  render(<ContextRail {...props} />)
  expect(screen.getByText('本次任务')).toBeInTheDocument()
  expect(screen.getByText('暂停')).toBeInTheDocument()
  expect(screen.getByText('当前进度')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- contextRail`
Expected: FAIL because the component does not exist.

**Step 3: Write minimal implementation**

- Add right-side rail showing:
  - mission summary
  - subject/topic/archive usage
  - progress and session state
  - jump links to draft cards
  - pause/resume/retry controls
- Reuse `RunPanel` data shape if helpful, but keep the new rail visually integrated with the studio.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- contextRail`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/aiGenerate/ContextRail.tsx frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/pages/questionLibrary/RunPanel.tsx frontend/src/pages/aiGenerate/__tests__/contextRail.test.tsx
git commit -m "feat(frontend): add ai generate context rail"
```

### Task 6: Add confirmed shelf, commit/discard controls, and single-card confirmation

**Files:**
- Create: `frontend/src/pages/aiGenerate/ConfirmedShelf.tsx`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/pages/aiGenerate/useAiGenerateSession.ts`
- Test: `frontend/src/pages/aiGenerate/__tests__/confirmedShelf.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmedShelf } from '@/pages/aiGenerate/ConfirmedShelf'

test('renders confirmed cards and commit action', async () => {
  render(<ConfirmedShelf {...props} />)
  expect(screen.getByText('已确认题目')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '全部入库' }))
  expect(props.onCommit).toHaveBeenCalled()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- confirmedShelf`
Expected: FAIL because the shelf component does not exist.

**Step 3: Write minimal implementation**

- Add confirmed shelf UI with:
  - confirmed count
  - horizontal/compact card summaries
  - remove from confirmed
  - commit all
  - discard session
- Bridge to existing preview commit/discard APIs.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- confirmedShelf`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/aiGenerate/ConfirmedShelf.tsx frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/pages/aiGenerate/useAiGenerateSession.ts frontend/src/pages/aiGenerate/__tests__/confirmedShelf.test.tsx
git commit -m "feat(frontend): add ai generate confirmed shelf"
```

### Task 7: Refresh the page visual system and responsive layout

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/components/layout/ManusLayout.tsx`
- Test: `frontend/src/pages/aiGenerate/__tests__/aiGenerateResponsive.test.tsx`

**Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import AiGeneratePage from '@/pages/AiGeneratePage'

test('keeps key studio regions visible on narrow viewports', () => {
  render(<AiGeneratePage />)
  expect(screen.getByText('AI 出题工作台')).toBeInTheDocument()
  expect(screen.getByText('本次任务')).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- aiGenerateResponsive`
Expected: FAIL if responsive shell regions are not rendered in the new layout.

**Step 3: Write minimal implementation**

- Add page-specific visual tokens/classes for:
  - warm paper background
  - radial glow
  - subtle grid/grain layer
  - elevated draft cards
- Ensure layout collapses cleanly on tablet/mobile:
  - mission bar stays top
  - context rail becomes drawer/stacked section
  - confirmed shelf remains accessible

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- aiGenerateResponsive`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/index.css frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx frontend/src/components/layout/ManusLayout.tsx frontend/src/pages/aiGenerate/__tests__/aiGenerateResponsive.test.tsx
git commit -m "feat(frontend): restyle ai generate studio"
```

### Task 8: Verify behavior, document screenshots, and request review

**Files:**
- Modify: `docs/plans/2026-03-13-ai-generate-studio-design.md`
- Optionally Modify: `README.md`
- Test: local verification artifacts/screenshots

**Step 1: Run focused frontend tests**

Run: `cd frontend && npm test -- aiGenerate`
Expected: PASS for all new AI generate tests.

**Step 2: Run lint**

Run: `cd frontend && npm run lint`
Expected: PASS

**Step 3: Run production build**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 4: Capture visual evidence**

Run the app locally and capture screenshots for:

- empty state
- generation in progress
- single-card editing
- confirmed shelf populated

**Step 5: Commit**

```bash
git add frontend/src docs/plans/2026-03-13-ai-generate-studio-design.md README.md
git commit -m "feat(frontend): redesign ai generate studio"
```
