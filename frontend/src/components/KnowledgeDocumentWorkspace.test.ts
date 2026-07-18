import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { documentApi } from '@/api/documents'
import type { DocumentDetail, DocumentPreview, DocumentSummary } from '@/types/document'

import KnowledgeDocumentWorkspace from './KnowledgeDocumentWorkspace.vue'

vi.mock('@/api/documents', () => ({
  documentApi: {
    list: vi.fn(),
    upload: vi.fn(),
    get: vi.fn(),
    preview: vi.fn(),
    rollback: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('@/api/tasks', () => ({
  taskApi: {
    get: vi.fn().mockResolvedValue({
      task_id: 'task-rollback',
      task_type: 'DOCUMENT_ROLLBACK',
      resource_type: 'DOCUMENT',
      resource_id: 'document-1',
      status: 'PENDING',
      stage: 'QUEUED',
      progress: 0,
      cancellable: true,
      retryable: false,
      attempt_count: 0,
      max_attempts: 3,
      error_code: null,
      error_message: null,
      files: [],
      result: null,
      created_at: '2026-07-17T08:00:00Z',
      updated_at: '2026-07-17T08:00:00Z',
      started_at: null,
      completed_at: null,
    }),
    cancel: vi.fn(),
    retry: vi.fn(),
  },
}))

const summary: DocumentSummary = {
  id: 'document-1',
  knowledge_base_id: 'kb-1',
  display_name: '校园咖啡馆指南.md',
  source_type: 'MD',
  mime_type: 'text/markdown',
  status: 'READY',
  current_version_no: 2,
  file_size: 2048,
  chunk_count: 2,
  last_error_code: null,
  created_at: '2026-07-16T08:00:00Z',
  updated_at: '2026-07-17T08:00:00Z',
}

const detail: DocumentDetail = {
  ...summary,
  source_key: 'uploads/campus-cafe.md',
  metadata: { category: '咖啡馆' },
  versions: [
    {
      id: 'version-2',
      version_no: 2,
      file_sha256: 'b'.repeat(64),
      file_size: 2048,
      parser_name: 'markdown',
      parser_version: '1.0',
      is_current: true,
      created_at: '2026-07-17T08:00:00Z',
    },
    {
      id: 'version-1',
      version_no: 1,
      file_sha256: 'a'.repeat(64),
      file_size: 1024,
      parser_name: 'markdown',
      parser_version: '1.0',
      is_current: false,
      created_at: '2026-07-16T08:00:00Z',
    },
  ],
}

const preview: DocumentPreview = {
  document_id: 'document-1',
  version_no: 2,
  original_content: '适合安静讨论的校园咖啡馆。',
  original_truncated: false,
  chunks: [
    {
      id: 'chunk-1',
      chunk_no: 0,
      content: '适合安静讨论。',
      token_count: 8,
      page_number: 1,
      metadata: {},
    },
  ],
  chunk_page: 1,
  chunk_page_size: 50,
  chunk_total: 1,
}

describe('KnowledgeDocumentWorkspace', () => {
  beforeEach(() => {
    vi.mocked(documentApi.list).mockReset().mockResolvedValue({
      items: [summary],
      page: 1,
      page_size: 10,
      total: 1,
    })
    vi.mocked(documentApi.get).mockReset().mockResolvedValue(detail)
    vi.mocked(documentApi.preview).mockReset().mockResolvedValue(preview)
    vi.mocked(documentApi.rollback).mockReset().mockResolvedValue({
      task_id: 'task-rollback',
      status: 'PENDING',
      progress: 0,
      status_url: '/api/v1/tasks/task-rollback',
    })
  })

  afterEach(() => vi.restoreAllMocks())

  it('opens original and Chunk previews for the selected immutable version', async () => {
    const wrapper = mount(KnowledgeDocumentWorkspace, {
      props: {
        knowledgeBaseId: 'kb-1',
        defaultChunkSize: 500,
        defaultChunkOverlap: 80,
        canManage: true,
      },
    })
    await flushPromises()

    await wrapper.get('tbody button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('适合安静讨论的校园咖啡馆。')
    await wrapper.findAll('.preview-tabs button')[1]?.trigger('click')
    expect(wrapper.text()).toContain('Chunk 0')
    expect(wrapper.text()).toContain('8 tokens · 第 1 页')
    expect(documentApi.preview).toHaveBeenCalledWith('document-1', {
      version_no: 2,
      keyword: undefined,
      chunk_page: 1,
      chunk_page_size: 50,
    })
  })

  it('requires confirmation before submitting a rollback task', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(KnowledgeDocumentWorkspace, {
      props: {
        knowledgeBaseId: 'kb-1',
        defaultChunkSize: 500,
        defaultChunkOverlap: 80,
        canManage: true,
      },
    })
    await flushPromises()
    await wrapper.get('tbody button').trigger('click')
    await flushPromises()

    await wrapper.get('.version-toolbar select').setValue(1)
    await flushPromises()
    await wrapper.get('.version-toolbar button').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('回滚到版本 1'))
    expect(documentApi.rollback).toHaveBeenCalledWith('document-1', 1)
    expect(wrapper.text()).toContain('版本回滚任务已提交：task-rollback')
  })
})
