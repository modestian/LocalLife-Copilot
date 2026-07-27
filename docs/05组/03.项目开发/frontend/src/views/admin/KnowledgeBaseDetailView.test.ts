import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { knowledgeBaseApi } from '@/api/knowledge-bases'
import type { KnowledgeBaseDetail } from '@/types/knowledge-base'

import KnowledgeBaseDetailView from './KnowledgeBaseDetailView.vue'

vi.mock('@/api/knowledge-bases', () => ({
  knowledgeBaseApi: {
    list: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
  },
}))

const detail: KnowledgeBaseDetail = {
  id: 'kb-public',
  name: '校园周边商家库',
  description: '公开商家资料',
  department_id: null,
  department_name: null,
  owner_id: 'owner-id',
  owner_name: '知识管理员',
  embedding_model_id: 'model-id',
  embedding_model_name: 'bge-small-zh-v1.5',
  chunk_size: 500,
  chunk_overlap: 80,
  status: 'ACTIVE',
  statistics: {
    document_count: 12,
    chunk_count: 320,
    ready_document_count: 11,
    failed_document_count: 1,
  },
  created_at: '2026-07-16T08:00:00Z',
  updated_at: '2026-07-17T08:00:00Z',
  latest_indexed_at: '2026-07-17T07:30:00Z',
}

describe('KnowledgeBaseDetailView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(knowledgeBaseApi.get).mockReset().mockResolvedValue(detail)
  })

  it('shows statistics but no edit controls to a guest', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'root', component: { template: '<div />' } },
        { path: '/admin', name: 'admin-home', component: { template: '<div />' } },
        { path: '/admin/knowledge-bases', name: 'knowledge-bases', component: { template: '<div />' } },
        {
          path: '/admin/knowledge-bases/:id',
          name: 'knowledge-base-detail',
          component: KnowledgeBaseDetailView,
        },
        { path: '/login', name: 'login', component: { template: '<div />' } },
      ],
    })
    await router.push('/admin/knowledge-bases/kb-public')
    await router.isReady()

    const wrapper = mount(KnowledgeBaseDetailView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('校园周边商家库')
    expect(wrapper.text()).toContain('320')
    expect(wrapper.text()).toContain('游客可以查看详情，但不能修改任何配置')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('编辑配置')
  })
})
