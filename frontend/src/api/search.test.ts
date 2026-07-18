import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { searchApi } from './search'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('search API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset().mockResolvedValue({ items: [] }))

  it('posts the documented hybrid-search contract', async () => {
    const payload = {
      query: '安静、适合四个人讨论的咖啡馆',
      knowledge_base_ids: ['kb-1'],
      top_k: 10,
      vector_weight: 0.6,
      keyword_weight: 0.4,
      rerank: true,
      filters: {
        category: ['咖啡馆'],
        price_cent_lte: 6000,
        distance_meter_lte: 3000,
        open_now: true,
        document_type: ['review' as const, 'merchant' as const],
      },
    }

    await searchApi.search(payload)

    expect(requestData).toHaveBeenCalledWith({
      method: 'POST',
      url: '/api/v1/search',
      data: payload,
    })
  })
})
