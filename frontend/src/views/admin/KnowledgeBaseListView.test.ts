import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { knowledgeBaseApi } from '@/api/knowledge-bases'
import { useAuthStore } from '@/stores/auth'

import KnowledgeBaseListView from './KnowledgeBaseListView.vue'

vi.mock('@/api/knowledge-bases', () => ({
  knowledgeBaseApi: {
    list: vi.fn(),
  },
}))

describe('KnowledgeBaseListView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(knowledgeBaseApi.list).mockReset().mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
    })
    useAuthStore().currentUser = {
      id: 'admin-id',
      username: 'admin',
      display_name: '平台管理员',
      email: null,
      department_id: '00000000-0000-4000-8000-000000000010',
      roles: [{ code: 'PLATFORM_ADMIN', name: '平台管理员' }],
      permissions: ['knowledge_base.read'],
      resource_scopes: [],
    }
  })

  it('uses the platform administrator department as the default tenant context', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/admin/knowledge-bases', component: KnowledgeBaseListView }],
    })
    await router.push('/admin/knowledge-bases')
    await router.isReady()

    const wrapper = mount(KnowledgeBaseListView, {
      global: {
        plugins: [router],
        stubs: { ProductTopBar: true },
      },
    })
    await flushPromises()

    const tenantInput = wrapper.get('input[placeholder="输入租户 UUID"]')
      .element as HTMLInputElement
    expect(tenantInput.value).toBe('00000000-0000-4000-8000-000000000010')
    expect(knowledgeBaseApi.list).toHaveBeenCalledWith({
      name: undefined,
      status: undefined,
      tenant_id: '00000000-0000-4000-8000-000000000010',
      department_id: undefined,
      page: 1,
      page_size: 10,
    })
  })

  it('renders normalized items when optional presentation fields are unavailable', async () => {
    vi.mocked(knowledgeBaseApi.list).mockResolvedValue({
      items: [
        {
          id: 'knowledge-base-id',
          name: '探店知识库',
          description: null,
          department_id: null,
          department_name: null,
          owner_id: '00000000-0000-4000-8000-000000001234',
          owner_name: '',
          embedding_model_id: '',
          embedding_model_name: '',
          chunk_size: 0,
          chunk_overlap: 0,
          status: 'ACTIVE',
          statistics: {
            document_count: 0,
            chunk_count: 0,
            ready_document_count: 0,
            failed_document_count: 0,
          },
          created_at: '',
          updated_at: '',
        },
      ],
      page: 1,
      page_size: 10,
      total: 1,
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/admin/knowledge-bases', component: KnowledgeBaseListView },
        {
          path: '/admin/knowledge-bases/:id',
          name: 'knowledge-base-detail',
          component: { template: '<div />' },
        },
      ],
    })
    await router.push('/admin/knowledge-bases')
    await router.isReady()

    const wrapper = mount(KnowledgeBaseListView, {
      global: {
        plugins: [router],
        stubs: { ProductTopBar: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('探店知识库')
    expect(wrapper.text()).toContain('用户 · 00001234')
    expect(wrapper.text()).toContain('暂无更新时间')
    expect(wrapper.text()).toContain('1 个知识库')
  })
})
