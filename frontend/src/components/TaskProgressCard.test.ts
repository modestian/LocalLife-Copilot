import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { taskApi } from '@/api/tasks'
import type { AcceptedTask, AsyncTaskDetail } from '@/types/task'

import TaskProgressCard from './TaskProgressCard.vue'

vi.mock('@/api/tasks', () => ({
  taskApi: {
    get: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
  },
}))

const accepted: AcceptedTask = {
  task_id: 'task-1',
  status: 'PENDING',
  progress: 0,
  status_url: '/api/v1/tasks/task-1',
}

function taskDetail(overrides: Partial<AsyncTaskDetail> = {}): AsyncTaskDetail {
  return {
    task_id: 'task-1',
    task_type: 'DOCUMENT_INGEST',
    resource_type: 'KNOWLEDGE_BASE',
    resource_id: 'kb-1',
    status: 'RUNNING',
    stage: 'CLEANING',
    progress: 35,
    cancellable: true,
    retryable: false,
    attempt_count: 1,
    max_attempts: 3,
    error_code: null,
    error_message: null,
    files: [
      {
        file_name: 'menu.csv',
        document_id: 'document-1',
        status: 'RUNNING',
        stage: 'CLEANING',
        progress: 40,
        error_code: null,
        error_message: null,
      },
      {
        file_name: 'guide.pdf',
        document_id: 'document-2',
        status: 'PENDING',
        stage: 'QUEUED',
        progress: 0,
        error_code: null,
        error_message: null,
      },
    ],
    result: null,
    created_at: '2026-07-17T08:00:00Z',
    updated_at: '2026-07-17T08:01:00Z',
    started_at: '2026-07-17T08:00:10Z',
    completed_at: null,
    ...overrides,
  }
}

describe('TaskProgressCard', () => {
  beforeEach(() => {
    vi.mocked(taskApi.get).mockReset().mockResolvedValue(taskDetail())
    vi.mocked(taskApi.cancel).mockReset()
    vi.mocked(taskApi.retry).mockReset()
  })

  afterEach(() => vi.restoreAllMocks())

  it('shows aggregate progress, current stage and every uploaded file', async () => {
    const wrapper = mount(TaskProgressCard, {
      props: { task: accepted, fileNames: ['menu.csv', 'guide.pdf'], canManage: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('DOCUMENT_INGEST')
    expect(wrapper.text()).toContain('内容清洗')
    expect(wrapper.text()).toContain('35%')
    expect(wrapper.text()).toContain('menu.csv')
    expect(wrapper.text()).toContain('40%')
    expect(wrapper.text()).toContain('guide.pdf')
    expect(wrapper.findAll('.file-progress li')).toHaveLength(2)
    wrapper.unmount()
  })

  it('disables cancellation after the task enters a non-interruptible stage', async () => {
    vi.mocked(taskApi.get).mockResolvedValue(taskDetail({
      stage: 'INDEXING',
      progress: 80,
      cancellable: false,
    }))
    const wrapper = mount(TaskProgressCard, {
      props: { task: accepted, canManage: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('任务已进入不可中断阶段')
    expect(wrapper.get('footer button').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('shows failure details and submits an allowed retry', async () => {
    const failed = taskDetail({
      status: 'FAILED',
      stage: 'SPLITTING',
      progress: 45,
      cancellable: false,
      retryable: true,
      attempt_count: 1,
      error_code: 'SPLITTING_FAILED',
      error_message: '切分参数无效',
      completed_at: '2026-07-17T08:02:00Z',
      files: [],
    })
    const pending = taskDetail({
      status: 'PENDING',
      stage: 'QUEUED',
      progress: 0,
      cancellable: true,
      retryable: false,
      attempt_count: 2,
      error_code: null,
      error_message: null,
      completed_at: null,
      files: [],
    })
    vi.mocked(taskApi.get).mockResolvedValueOnce(failed).mockResolvedValueOnce(pending)
    vi.mocked(taskApi.retry).mockResolvedValue({ ...accepted, status: 'PENDING' })
    const wrapper = mount(TaskProgressCard, {
      props: { task: { ...accepted, status: 'FAILED', progress: 45 }, canManage: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('SPLITTING_FAILED')
    expect(wrapper.text()).toContain('失败阶段：文档切分')
    expect(wrapper.text()).toContain('切分参数无效')
    await wrapper.get('.retry-button').trigger('click')
    await flushPromises()

    expect(taskApi.retry).toHaveBeenCalledWith('task-1')
    expect(wrapper.text()).toContain('等待处理')
    wrapper.unmount()
  })

  it('sends cancellation only while the server marks the task cancellable', async () => {
    const cancelled = taskDetail({
      status: 'CANCELLED',
      stage: 'CLEANING',
      progress: 35,
      cancellable: false,
      completed_at: '2026-07-17T08:01:30Z',
    })
    vi.mocked(taskApi.get).mockResolvedValueOnce(taskDetail()).mockResolvedValueOnce(cancelled)
    vi.mocked(taskApi.cancel).mockResolvedValue({
      ...accepted,
      status: 'RUNNING',
      progress: 35,
    })
    const wrapper = mount(TaskProgressCard, {
      props: { task: accepted, canManage: true },
    })
    await flushPromises()
    const cancelButton = wrapper.findAll('footer button')[0]
    await cancelButton?.trigger('click')
    await flushPromises()

    expect(taskApi.cancel).toHaveBeenCalledWith('task-1')
    expect(wrapper.text()).toContain('已取消')
    wrapper.unmount()
  })
})
