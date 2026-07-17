import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { knowledgeBaseApi } from './knowledge-bases'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('knowledge base API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset())

  it('sends list filters using the documented contract', async () => {
    vi.mocked(requestData).mockResolvedValue({ items: [], page: 2, page_size: 10, total: 0 })

    await knowledgeBaseApi.list({ name: '校园', status: 'ACTIVE', page: 2, page_size: 10 })

    expect(requestData).toHaveBeenCalledWith({
      method: 'GET',
      url: '/api/v1/knowledge-bases',
      params: { name: '校园', status: 'ACTIVE', page: 2, page_size: 10 },
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
