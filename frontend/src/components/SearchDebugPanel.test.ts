import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { SearchResult } from '@/api/search'

import SearchDebugPanel from './SearchDebugPanel.vue'

const result: SearchResult = {
  chunk_id: 'chunk-001',
  document_id: 'document-001',
  merchant_id: 'merchant-001',
  content: '环境安静，靠窗位置适合四人讨论，工作日下午客流较少。',
  source_location: '点评 / 星光咖啡 / 2026-07-12',
  source_url: '/app/reviews/review-001',
  score: 0.824,
  score_detail: { bm25: 0.612, vector: 0.887, fusion: 0.846 },
}

describe('SearchDebugPanel', () => {
  it('submits query filters and renders dual-route scores', async () => {
    const search = vi.fn().mockResolvedValue([result])
    const wrapper = mount(SearchDebugPanel, {
      props: { knowledgeBaseId: 'kb-001', search },
    })

    await wrapper.get('form').trigger('submit')

    expect(search).toHaveBeenCalledWith(expect.objectContaining({
      query: '安静、适合四人讨论的咖啡馆',
      knowledge_base_ids: ['kb-001'],
      filters: expect.objectContaining({
        category: ['咖啡馆'],
        distance_meter_lte: 3000,
        price_cent_lte: 6000,
        open_now: true,
      }),
    }))
    expect(wrapper.text()).toContain('BM25')
    expect(wrapper.text()).toContain('0.612')
    expect(wrapper.text()).toContain('0.887')
    expect(wrapper.text()).toContain('0.846')
  })

  it('opens a citation preview for a result', async () => {
    const wrapper = mount(SearchDebugPanel, {
      props: { knowledgeBaseId: 'kb-001', initialResults: [result] },
    })

    await wrapper.get('.search-result__preview').trigger('click')

    expect(wrapper.get('[role="dialog"]').text()).toContain('环境安静')
    expect(wrapper.get('[role="dialog"]').text()).toContain('chunk-001')
    expect(wrapper.get('[role="dialog"] a').attributes('href')).toBe('/app/reviews/review-001')
  })

  it('shows an empty state for a valid query without matches', async () => {
    const search = vi.fn().mockResolvedValue([])
    const wrapper = mount(SearchDebugPanel, {
      props: { knowledgeBaseId: 'kb-001', search },
    })

    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('没有符合当前筛选条件的结果')
  })
})
