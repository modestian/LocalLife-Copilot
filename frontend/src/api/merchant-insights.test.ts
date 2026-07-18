import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { merchantInsightsApi } from './merchant-insights'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('merchant insights API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset().mockResolvedValue({}))

  it('posts a shared comparison window and merchant set', async () => {
    const payload = {
      merchant_ids: ['merchant-self', 'competitor-a', 'competitor-b'],
      start_date: '2026-07-01T00:00:00',
      end_date: '2026-08-01T00:00:00',
    }

    await merchantInsightsApi.compare(payload)

    expect(requestData).toHaveBeenCalledWith({
      method: 'POST',
      url: '/api/v1/merchants/compare',
      data: payload,
    })
  })

  it('posts editable-reply and evidence-backed business-suggestion requests', async () => {
    await merchantInsightsApi.getReplySuggestion('review/id', {
      tone: 'EMPATHETIC',
      aspect_labels: ['服务'],
      prohibited_commitments: ['虚构补偿'],
    })
    await merchantInsightsApi.getBusinessSuggestions('merchant/id', {
      focus_aspects: ['服务'],
      start_date: '2026-07-01T00:00:00',
    })

    expect(requestData).toHaveBeenNthCalledWith(1, {
      method: 'POST',
      url: '/api/v1/reviews/review%2Fid/reply-suggestions',
      data: {
        tone: 'EMPATHETIC',
        aspect_labels: ['服务'],
        prohibited_commitments: ['虚构补偿'],
      },
    })
    expect(requestData).toHaveBeenNthCalledWith(2, {
      method: 'POST',
      url: '/api/v1/merchants/merchant%2Fid/business-suggestions',
      data: {
        focus_aspects: ['服务'],
        start_date: '2026-07-01T00:00:00',
      },
    })
  })
})
