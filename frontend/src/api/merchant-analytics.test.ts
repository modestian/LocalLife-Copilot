import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { merchantAnalyticsApi } from './merchant-analytics'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('merchant analytics API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset().mockResolvedValue([]))

  it('requests the sentiment trend with documented granularity and time filters', async () => {
    await merchantAnalyticsApi.getSentimentTrend('merchant/001', {
      granularity: 'week',
      start_date: '2026-07-01T00:00:00',
      end_date: '2026-08-01T00:00:00',
    })

    expect(requestData).toHaveBeenCalledWith({
      method: 'GET',
      url: '/api/v1/merchants/merchant%2F001/analytics/sentiment-trend',
      params: {
        granularity: 'week',
        start_date: '2026-07-01T00:00:00',
        end_date: '2026-08-01T00:00:00',
      },
    })
  })

  it('requests negative attribution and review drill-down resources', async () => {
    await merchantAnalyticsApi.getNegativeReasons('merchant-1', {
      start_date: '2026-07-01T00:00:00',
    })
    await merchantAnalyticsApi.getReviews('merchant-1', {
      sentiment: 'NEGATIVE',
      negative_reason: '服务响应慢',
      limit: 50,
      offset: 0,
    })

    expect(requestData).toHaveBeenNthCalledWith(1, {
      method: 'GET',
      url: '/api/v1/merchants/merchant-1/analytics/negative-reasons',
      params: { start_date: '2026-07-01T00:00:00' },
    })
    expect(requestData).toHaveBeenNthCalledWith(2, {
      method: 'GET',
      url: '/api/v1/merchants/merchant-1/analytics/reviews',
      params: {
        sentiment: 'NEGATIVE',
        negative_reason: '服务响应慢',
        limit: 50,
        offset: 0,
      },
    })
  })
})
