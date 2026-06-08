import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TemplatesPage from '@/pages/TemplatesPage'
import * as templatesApi from '@/api/templates'
import { useNotificationStore } from '@/stores/useNotificationStore'

vi.mock('@/api/templates', () => ({
  createTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  exportTemplates: vi.fn(),
  importTemplates: vi.fn(),
  listTemplates: vi.fn(),
  updateTemplate: vi.fn(),
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <TemplatesPage />
    </QueryClientProvider>,
  )
}

describe('TemplatesPage', () => {
  beforeEach(() => {
    vi.mocked(templatesApi.listTemplates).mockResolvedValue([])
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  it('invalidates the templates query and shows a success toast after importing templates', async () => {
    vi.mocked(templatesApi.importTemplates).mockResolvedValue([
      { id: 2, template_type: 'study_materials', name: '导入模板', body: {} },
    ])
    const { container } = renderPage()

    await waitFor(() => expect(templatesApi.listTemplates).toHaveBeenCalledTimes(1))

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(
      [JSON.stringify({ templates: [{ id: 2, template_type: 'study_materials', name: '导入模板', body: {} }] })],
      'templates.json',
      { type: 'application/json' },
    )
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(templatesApi.importTemplates).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(templatesApi.listTemplates).toHaveBeenCalledTimes(2))
    expect(useNotificationStore.getState().toasts).toEqual(
      expect.arrayContaining([expect.objectContaining({ title: '已导入 1 个模板', status: 'completed' })]),
    )
  })

  it('shows a failed toast when importing templates fails', async () => {
    vi.mocked(templatesApi.importTemplates).mockRejectedValue(new Error('导入格式错误'))
    const { container } = renderPage()

    await waitFor(() => expect(templatesApi.listTemplates).toHaveBeenCalledTimes(1))

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File([JSON.stringify({ templates: [] })], 'templates.json', { type: 'application/json' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => {
      expect(useNotificationStore.getState().toasts).toEqual(
        expect.arrayContaining([expect.objectContaining({ title: '导入格式错误', status: 'failed' })]),
      )
    })
  })

  it('does not silently save non-object JSON bodies as an empty object', async () => {
    const user = userEvent.setup()
    vi.mocked(templatesApi.createTemplate).mockResolvedValue({
      id: 3,
      template_type: 'study_materials',
      name: '新模板',
      body: {},
    })
    renderPage()

    await user.click(screen.getByRole('button', { name: /新建/ }))
    await user.type(screen.getByPlaceholderText('给模板起个名字'), '新模板')
    const bodyInput = screen.getByDisplayValue('{}')
    fireEvent.change(bodyInput, { target: { value: '[]' } })
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(templatesApi.createTemplate).not.toHaveBeenCalled()
    expect(await screen.findByText('模板内容必须是 JSON 对象')).toBeInTheDocument()
  })
})
