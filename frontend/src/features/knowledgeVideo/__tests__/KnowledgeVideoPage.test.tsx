import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import KnowledgeVideoPage from '@/features/knowledgeVideo/KnowledgeVideoPage'
import * as knowledgeVideosApi from '@/api/knowledgeVideos'
import * as tasksApi from '@/api/tasks'

vi.mock('@/api/knowledgeVideos', () => ({
  generateKnowledgeVideo: vi.fn(),
}))

vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
  streamTask: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: vi.fn(async () => ({ objectUrl: 'blob:video', revoke: vi.fn(), filename: 'video.mp4' })),
  downloadText: vi.fn(async () => 'class KnowledgeVideoScene(Scene): pass'),
}))

describe('KnowledgeVideoPage', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    class MockResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver
    window.scrollTo = vi.fn()
  })

  it('submits topic and streams completed task result', async () => {
    vi.mocked(knowledgeVideosApi.generateKnowledgeVideo).mockResolvedValue({ taskId: 'knowledge-video-1' })
    vi.mocked(tasksApi.getTask).mockResolvedValue({
      id: 'knowledge-video-1',
      status: 'completed',
      result: {
        video_url: '/api/media/generated/video.mp4',
        subtitle_url: '/api/media/generated/subtitle.srt',
        script_url: '/api/media/generated/script.py',
        metadata: { attempts: 1, scene_name: 'KnowledgeVideoScene' },
      },
    })
    vi.mocked(tasksApi.streamTask).mockImplementation((_taskId, _afterSeq, onEvent, _onError, onComplete) => {
      onEvent({
        taskId: 'knowledge-video-1',
        seq: 1,
        type: 'progress',
        data: { stage_id: 'render', stage_label: 'Docker 沙盒渲染', progress: 70 },
      })
      onComplete?.()
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <KnowledgeVideoPage />
      </MemoryRouter>
    )

    await user.type(screen.getByLabelText('主题'), '导数的几何意义')
    await user.click(screen.getByRole('button', { name: '生成视频' }))

    expect(knowledgeVideosApi.generateKnowledgeVideo).toHaveBeenCalledWith(
      expect.objectContaining({ topic: '导数的几何意义' })
    )

    await waitFor(() => {
      expect(screen.getByText('knowledge-video-1')).toBeInTheDocument()
      expect(screen.getByText('Docker 沙盒渲染')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '下载字幕' })).toBeInTheDocument()
      expect(screen.getByText('/api/media/generated/script.py')).toBeInTheDocument()
      expect(screen.getByText('class KnowledgeVideoScene(Scene): pass')).toBeInTheDocument()
    })
  })

  it('restores a completed task from the task query parameter', async () => {
    vi.mocked(tasksApi.getTask).mockResolvedValue({
      id: 'knowledge-video-1',
      status: 'completed',
      progress: 100,
      result: {
        video_url: '/api/media/generated/video.mp4',
        subtitle_url: '/api/media/generated/subtitle.srt',
        script_url: '/api/media/generated/script.py',
        metadata: { attempts: 1, scene_name: 'KnowledgeVideoScene' },
      },
    })

    render(
      <MemoryRouter initialEntries={['/knowledge-videos?task=knowledge-video-1']}>
        <KnowledgeVideoPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(tasksApi.getTask).toHaveBeenCalledWith('knowledge-video-1')
      expect(screen.getByText('knowledge-video-1')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '下载视频' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '下载字幕' })).toBeInTheDocument()
      expect(screen.getByText('/api/media/generated/script.py')).toBeInTheDocument()
    })
  })
})
