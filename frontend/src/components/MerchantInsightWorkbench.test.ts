import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { merchantAnalyticsApi } from '@/api/merchant-analytics'
import { merchantInsightsApi } from '@/api/merchant-insights'

import MerchantInsightWorkbench from './MerchantInsightWorkbench.vue'

vi.mock('@/api/merchant-analytics', () => ({ merchantAnalyticsApi: { getReviews: vi.fn() } }))
vi.mock('@/api/merchant-insights', () => ({
  merchantInsightsApi: {
    compare: vi.fn(),
    getReplySuggestion: vi.fn(),
    getBusinessSuggestions: vi.fn(),
  },
}))

describe('MerchantInsightWorkbench', () => {
  beforeEach(() => {
    vi.mocked(merchantAnalyticsApi.getReviews).mockReset().mockResolvedValue([
      {
        id: 'review-1',
        review_text: '等位时间太久，服务响应也不及时。',
        sentiment: 'NEGATIVE',
        confidence: 0.92,
        aspect_labels: ['服务', '等位'],
        negative_reasons: ['服务响应慢'],
        review_date: '2026-07-16T12:00:00',
      },
    ])
    vi.mocked(merchantInsightsApi.compare).mockReset().mockResolvedValue({
      period_start: '2026-07-01T00:00:00',
      period_end: '2026-07-31T00:00:00',
      metric_definition: '同一时间窗内的公开点评聚合',
      minimum_sample_size: 10,
      insufficient_data: false,
      merchants: [
        {
          merchant_id: 'merchant-self',
          merchant_name: '本店',
          sample_count: 32,
          positive_rate: 0.75,
          avg_rating: 4.3,
          aspect_counts: { 服务: 12 },
          negative_reason_counts: { 等位时间长: 4 },
        },
      ],
    })
    vi.mocked(merchantInsightsApi.getReplySuggestion).mockReset().mockResolvedValue({
      draft: '很抱歉让您久等了，我们会优化高峰时段的接待安排。',
      model_version: 'sentiment-v1',
      prompt_version: 'reply-v2',
      generated_at: '2026-07-18T08:00:00',
      evidence_review_ids: ['review-1'],
    })
    vi.mocked(merchantInsightsApi.getBusinessSuggestions).mockReset().mockResolvedValue({
      insufficient_data: false,
      evidence_conflict: false,
      model_version: 'insight-v1',
      prompt_version: 'business-v2',
      generated_at: '2026-07-18T08:00:00',
      suggestions: [
        {
          id: 'suggestion-1',
          title: '优化高峰时段等位分流',
          content: '在高峰时段增加等位预估和服务响应巡检。',
          confidence: 0.84,
          period_start: '2026-07-01T00:00:00',
          period_end: '2026-07-31T00:00:00',
          evidence_review_ids: ['review-1'],
          evidence_reviews: [
            {
              review_id: 'review-1',
              review_text: '等位时间太久，服务响应也不及时。',
              sentiment: 'NEGATIVE',
              reviewed_at: '2026-07-16T12:00:00',
            },
          ],
        },
      ],
    })
  })

  it('requires two to four competitors and compares under one shared window', async () => {
    const wrapper = mount(MerchantInsightWorkbench, { props: { merchantId: 'merchant-self' } })
    await flushPromises()
    const competitorInput = wrapper.get('[placeholder="输入后添加"]')

    await competitorInput.setValue('competitor-a')
    await wrapper.find('.compare-form button[type="button"]').trigger('click')
    await competitorInput.setValue('competitor-b')
    await wrapper.find('.compare-form button[type="button"]').trigger('click')
    await wrapper.get('.compare-form input[type="date"]').setValue('2026-07-01')
    await wrapper.findAll('.compare-form input[type="date"]')[1]?.setValue('2026-07-31')
    await wrapper.get('.compare-form').trigger('submit')
    await flushPromises()

    expect(merchantInsightsApi.compare).toHaveBeenCalledWith({
      merchant_ids: ['merchant-self', 'competitor-a', 'competitor-b'],
      start_date: '2026-07-01T00:00:00',
      end_date: '2026-08-01T00:00:00',
    })
    expect(wrapper.text()).toContain('本店')
    expect(wrapper.text()).toContain('同一时间窗内的公开点评聚合')
    expect(wrapper.text()).toContain('等位时间长 4')
  })

  it('generates an editable reply draft and exposes no publishing control', async () => {
    const wrapper = mount(MerchantInsightWorkbench, { props: { merchantId: 'merchant-self' } })
    await flushPromises()

    await wrapper.findAll('.reply-controls .primary-button')[0]?.trigger('click')
    await flushPromises()

    expect(merchantInsightsApi.getReplySuggestion).toHaveBeenCalledWith('review-1', {
      tone: 'EMPATHETIC',
      aspect_labels: ['服务', '等位'],
      prohibited_commitments: ['虚构补偿', '虚构联系方式', '虚构已完成整改'],
    })
    expect(wrapper.get('[data-testid="reply-draft"]').element.value).toContain('很抱歉让您久等了')
    expect(wrapper.text()).toContain('不会自动发布')
    expect(wrapper.findAll('button').some((button) => button.text().includes('发布'))).toBe(false)
  })

  it('displays business suggestions with expandable review evidence', async () => {
    const wrapper = mount(MerchantInsightWorkbench, { props: { merchantId: 'merchant-self' } })
    await flushPromises()

    await wrapper.get('.suggestion-form').trigger('submit')
    await flushPromises()

    expect(merchantInsightsApi.getBusinessSuggestions).toHaveBeenCalledWith('merchant-self', {})
    const detail = wrapper.get('.suggestion-detail')
    expect(detail.text()).toContain('优化高峰时段等位分流')
    expect(detail.text()).toContain('证据点评（1）')
    expect(detail.text()).toContain('等位时间太久')
    expect(wrapper.text()).toContain('模型 insight-v1')
  })
})
