import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type {
  MerchantRecommendation,
  RecommendationSource,
} from '@/types/recommendation'

import RecommendationResults from './RecommendationResults.vue'

const recommendation: MerchantRecommendation = {
  merchant_id: 'merchant-001',
  name: '星光咖啡',
  category: '咖啡馆',
  reason: '环境安静、工作日下午客流较少，适合四人讨论。',
  distance_meter: 850,
  avg_price_cent: 5800,
  rating: 4.6,
  business_status: 'OPEN',
  data_updated_at: '2026-07-17T04:00:00Z',
  source_chunk_ids: ['chunk-001'],
  tags: ['安静', '有插座'],
}

const source: RecommendationSource = {
  chunk_id: 'chunk-001',
  source_location: '点评 / 星光咖啡 / 2026-07-16',
  source_url: '/app/reviews/review-001#chunk-001',
  content: '工作日下午客流较少，靠窗位置安静，而且每张桌子附近都有插座。',
  highlight_text: '靠窗位置安静',
  score: 0.91,
}

describe('RecommendationResults', () => {
  it('renders recommendation facts, freshness and the AI boundary', () => {
    const wrapper = mount(RecommendationResults, {
      props: {
        recommendations: [recommendation],
        sources: [source],
        now: '2026-07-17T05:00:00Z',
      },
    })

    expect(wrapper.text()).toContain('星光咖啡')
    expect(wrapper.text()).toContain('850 米')
    expect(wrapper.text()).toContain('人均 ¥58')
    expect(wrapper.text()).toContain('24 小时内更新')
    expect(wrapper.text()).toContain('AI 使用边界')
  })

  it('opens the source snapshot and highlights the supporting fragment', async () => {
    const wrapper = mount(RecommendationResults, {
      props: { recommendations: [recommendation], sources: [source] },
    })

    await wrapper.get('.recommendation-card__sources').trigger('click')

    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('点评 / 星光咖啡')
    expect(dialog.get('mark').text()).toBe('靠窗位置安静')
    expect(dialog.get('a').attributes()).toMatchObject({
      href: '/app/reviews/review-001#chunk-001',
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('shows an explicit stale-data warning', () => {
    const wrapper = mount(RecommendationResults, {
      props: {
        recommendations: [{ ...recommendation, data_updated_at: '2026-05-01T00:00:00Z' }],
        sources: [source],
        now: '2026-07-17T05:00:00Z',
      },
    })

    expect(wrapper.get('[data-level="stale"]').text()).toContain('数据可能已过期')
  })

  it('rejects unsafe source links', async () => {
    const wrapper = mount(RecommendationResults, {
      props: {
        recommendations: [recommendation],
        sources: [{ ...source, source_url: 'javascript:alert(1)' }],
      },
    })

    await wrapper.get('.recommendation-card__sources').trigger('click')

    expect(wrapper.get('[role="dialog"] a').attributes('href')).toBe('#')
  })

  it('hides recommendation cards and emits a refinement from fallback state', async () => {
    const wrapper = mount(RecommendationResults, {
      props: {
        recommendations: [recommendation],
        sources: [source],
        fallback: {
          triggered: true,
          reason: '当前仅有一条低相关证据，无法可靠推荐。',
          suggestions: ['扩大到 5 公里'],
        },
      },
    })

    expect(wrapper.text()).toContain('没有足够证据')
    expect(wrapper.text()).toContain('无法可靠推荐')
    expect(wrapper.find('.recommendation-card').exists()).toBe(false)
    await wrapper.get('.recommendation-fallback__actions button').trigger('click')
    expect(wrapper.emitted('refine')).toEqual([['扩大到 5 公里']])
  })
})
