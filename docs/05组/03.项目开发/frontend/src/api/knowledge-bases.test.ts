import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { knowledgeBaseApi } from './knowledge-bases'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('knowledge base API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset())

  it('sends list filters using the documented contract', async () => {
    vi.mocked(requestData).mockResolvedValue({ items: [], page: 2, page_size: 10, total: 0 })

    await knowledgeBaseApi.list({
      tenant_id: 'tenant-id',
      department_id: 'department-id',
      name: '校园',
      status: 'ACTIVE',
      page: 2,
      page_size: 10,
    })

    expect(requestData).toHaveBeenCalledWith({
      method: 'GET',
      url: '/api/v1/knowledge-bases',
      params: {
        tenant_id: 'tenant-id',
        department_id: 'department-id',
        name: '校园',
        status: 'ACTIVE',
        page: 2,
        page_size: 10,
      },
    })
  })

  it('normalizes sparse backend list items so the page can render safely', async () => {
    vi.mocked(requestData).mockResolvedValue({
      items: [
        {
          id: 'knowledge-base-id',
          owner_id: 'owner-id',
          name: '探店知识库',
          status: 'ACTIVE',
          department_id: null,
          description: null,
        },
      ],
      page: 1,
      page_size: 10,
      total: 1,
    })

    const result = await knowledgeBaseApi.list({ page: 1, page_size: 10 })

    expect(result.items[0]).toMatchObject({
      owner_name: '',
      updated_at: '',
      statistics: {
        document_count: 0,
        chunk_count: 0,
        ready_document_count: 0,
        failed_document_count: 0,
      },
    })
  })

  it('uses PATCH for editable knowledge base fields', async () => {
    const payload = {
      name: '校园周边商家库',
      description: '公开商家资料',
      owner_id: 'owner-id',
      embedding_model_id: 'bge-small-zh-v1.5',
    }
    vi.mocked(requestData).mockResolvedValue({})

    await knowledgeBaseApi.update('kb/id', payload)

    expect(requestData).toHaveBeenCalledWith({
      method: 'PATCH',
      url: '/api/v1/knowledge-bases/kb%2Fid',
      data: payload,
    })
  })
})
