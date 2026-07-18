import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { merchantAnalyticsApi } from '@/api/merchant-analytics'
import type { AnalyticsReview } from '@/types/merchant-analytics'

import MerchantAnalyticsDashboard from './MerchantAnalyticsDashboard.vue'

vi.mock('@/api/merchant-analytics', () => ({
  merchantAnalyticsApi: {
    getSentimentTrend: vi.fn(),
    getNegativeReasons: vi.fn(),
    getReviews: vi.fn(),
  },
}))

const reviews: AnalyticsReview[] = [
  {
    id: 'review-positive',
    review_text: '招牌菜很好吃，环境也很舒服。',
    sentiment: 'POSITIVE',
    confidence: 0.96,
    aspect_labels: ['菜品', '环境'],
    negative_reasons: [],
    review_date: '2026-07-16T12:30:00',
  },
  {
    id: 'review-negative',
    review_text: '等位很久，服务响应也比较慢。',
    sentiment: 'NEGATIVE',
    confidence: 0.88,
    aspect_labels: ['服务'],
    negative_reasons: ['服务响应慢'],
    review_date: '2026-07-17T18:20:00',
  },
]

describe('MerchantAnalyticsDashboard', () => {
  beforeEach(() => {
    vi.mocked(merchantAnalyticsApi.getSentimentTrend).mockReset().mockResolvedValue([
      { period: '2026-07-16', positive: 8, neutral: 1, negative: 1 },
      { period: '2026-07-17', positive: 4, neutral: 2, negative: 2 },
    ])
    vi.mocked(merchantAnalyticsApi.getNegativeReasons).mockReset().mockResolvedValue([
      { reason: '服务响应慢', count: 2 },
    ])
    vi.mocked(merchantAnalyticsApi.getReviews).mockReset().mockResolvedValue(reviews)
  })

  it('renders sentiment, trend, aspect and attribution data with sample counts', async () => {
    const wrapper = mount(MerchantAnalyticsDashboard, { props: { merchantId: 'merchant-1' } })
    await flushPromises()

    expect(wrapper.text()).toContain('分析样本')
    expect(wrapper.text()).toContain('18')
    expect(wrapper.text()).toContain('67%')
    expect(wrapper.text()).toContain('2026-07-16')
    expect(wrapper.text()).toContain('菜品')
    expect(wrapper.text()).toContain('服务响应慢')
    expect(merchantAnalyticsApi.getReviews).toHaveBeenCalledWith('merchant-1', {
      limit: 200,
      offset: 0,
    })
  })

  it('converts an inclusive date form into the backend exclusive end date', async () => {
    const wrapper = mount(MerchantAnalyticsDashboard, { props: { merchantId: 'merchant-1' } })
    await flushPromises()
    vi.mocked(merchantAnalyticsApi.getSentimentTrend).mockClear()

    await wrapper.get('[data-testid="granularity-filter"]').setValue('week')
    await wrapper.get('[data-testid="start-date-filter"]').setValue('2026-07-01')
    await wrapper.get('[data-testid="end-date-filter"]').setValue('2026-07-31')
    await wrapper.get('.analytics-filters').trigger('submit')
    await flushPromises()

    expect(merchantAnalyticsApi.getSentimentTrend).toHaveBeenCalledWith('merchant-1', {
      granularity: 'week',
      start_date: '2026-07-01T00:00:00',
      end_date: '2026-08-01T00:00:00',
    })
  })

  it('drills a negative attribution down through the review API', async () => {
    const wrapper = mount(MerchantAnalyticsDashboard, { props: { merchantId: 'merchant-1' } })
    await flushPromises()
    vi.mocked(merchantAnalyticsApi.getReviews).mockClear()

    await wrapper.get('[data-testid="reason-服务响应慢"]').trigger('click')
    await flushPromises()

    expect(merchantAnalyticsApi.getReviews).toHaveBeenCalledWith('merchant-1', {
      sentiment: 'NEGATIVE',
      negative_reason: '服务响应慢',
      limit: 50,
      offset: 0,
    })
    expect(wrapper.get('[role="dialog"]').text()).toContain('差评归因「服务响应慢」')
    expect(wrapper.get('[role="dialog"]').text()).toContain('等位很久')
    expect(wrapper.get('[role="dialog"]').text()).toContain('置信度 88%')
  })

  it('filters aspect drill-down from the review aspect labels', async () => {
    const wrapper = mount(MerchantAnalyticsDashboard, { props: { merchantId: 'merchant-1' } })
    await flushPromises()
    const aspectButton = wrapper.findAll('.rank-chart:not(.is-reason) button')
      .find((button) => button.text().includes('菜品'))

    expect(aspectButton).toBeDefined()
    await aspectButton?.trigger('click')

    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('特征「菜品」相关点评')
    expect(dialog.text()).toContain('招牌菜很好吃')
    expect(dialog.text()).not.toContain('等位很久')
  })
})
