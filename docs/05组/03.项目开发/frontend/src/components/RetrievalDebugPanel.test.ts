import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { searchApi } from '@/api/search'
import type { SearchHit } from '@/types/search'

import RetrievalDebugPanel from './RetrievalDebugPanel.vue'

vi.mock('@/api/search', () => ({
  searchApi: { search: vi.fn() },
}))

const hit: SearchHit = {
  chunk_id: 'chunk-1',
  document_id: 'document-1',
  merchant_id: 'merchant-1',
  content: '环境安静，靠窗位置适合四个人讨论，人均消费约 58 元。',
  source_location: '点评 / 星光咖啡 / 2026-07-16',
  source_url: '/app/reviews/review-1#chunk-1',
  score: 0.87,
  score_detail: {
    bm25: 8.4312,
    vector: 0.9134,
    fusion: 0.0328,
    rerank: 0.87,
  },
  match_explanation: {
    recall_sources: ['bm25', 'vector'],
    keyword_matched: true,
    semantic_matched: true,
    reranked: true,
  },
}

describe('RetrievalDebugPanel', () => {
  beforeEach(() => {
    vi.mocked(searchApi.search).mockReset().mockResolvedValue({
      items: [hit],
      total: 1,
      took_ms: 42,
      fallback: false,
      applied_filters: {},
    })
  })

  it('converts visible filters into the documented search request', async () => {
    const wrapper = mount(RetrievalDebugPanel, { props: { knowledgeBaseId: 'kb-1' } })

    await wrapper.get('[data-testid="search-query"]').setValue('安静的咖啡馆')
    await wrapper.get('[data-testid="category-filter"]').setValue('咖啡馆，甜品店')
    await wrapper.get('[data-testid="price-filter"]').setValue(60)
    await wrapper.get('[data-testid="distance-filter"]').setValue(3000)
    await wrapper.get('[data-testid="open-now-filter"]').setValue('true')
    await wrapper.get('input[value="review"]').setValue(true)
    await wrapper.get('[data-testid="search-submit"]').trigger('submit')
    await flushPromises()

    expect(searchApi.search).toHaveBeenCalledWith({
      query: '安静的咖啡馆',
      knowledge_base_ids: ['kb-1'],
      top_k: 10,
      vector_weight: 0.6,
      keyword_weight: 0.4,
      rerank: true,
      filters: {
        category: ['咖啡馆', '甜品店'],
        price_cent_lte: 6000,
        distance_meter_lte: 3000,
        open_now: true,
        document_type: ['review'],
      },
    })
    expect(wrapper.text()).toContain('人均不超过 ¥60')
    expect(wrapper.text()).toContain('42 ms')
  })

  it('shows BM25, vector and fusion scores and opens the citation preview', async () => {
    const wrapper = mount(RetrievalDebugPanel, { props: { knowledgeBaseId: 'kb-1' } })
    await wrapper.get('[data-testid="search-query"]').setValue('四人讨论')
    await wrapper.get('[data-testid="search-submit"]').trigger('submit')
    await flushPromises()

    const card = wrapper.get('.result-card')
    expect(card.text()).toContain('BM25')
    expect(card.text()).toContain('8.4312')
    expect(card.text()).toContain('向量')
    expect(card.text()).toContain('0.9134')
    expect(card.text()).toContain('融合')
    expect(card.text()).toContain('0.0328')

    await card.get('footer button').trigger('click')
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('点评 / 星光咖啡 / 2026-07-16')
    expect(dialog.text()).toContain('靠窗位置适合四个人讨论')
    expect(dialog.get('a').attributes()).toMatchObject({
      href: '/app/reviews/review-1#chunk-1',
      target: '_blank',
      rel: 'noopener noreferrer',
    })
  })

  it('rejects weights that do not add up to one before calling the API', async () => {
    const wrapper = mount(RetrievalDebugPanel, { props: { knowledgeBaseId: 'kb-1' } })
    await wrapper.get('[data-testid="search-query"]').setValue('咖啡馆')
    const scoreInputs = wrapper.findAll('.score-fieldset input[type="number"]')
    await scoreInputs[1]?.setValue(0.8)
    await wrapper.get('[data-testid="search-submit"]').trigger('submit')

    expect(wrapper.text()).toContain('总和等于 1')
    expect(searchApi.search).not.toHaveBeenCalled()
  })

  it('rejects unsafe source links in the citation preview', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({
      items: [{ ...hit, source_url: 'javascript:alert(1)' }],
      fallback: false,
      applied_filters: {},
    })
    const wrapper = mount(RetrievalDebugPanel, { props: { knowledgeBaseId: 'kb-1' } })
    await wrapper.get('[data-testid="search-query"]').setValue('咖啡馆')
    await wrapper.get('[data-testid="search-submit"]').trigger('submit')
    await flushPromises()
    await wrapper.get('.result-card footer button').trigger('click')

    expect(wrapper.get('[role="dialog"] a').attributes('href')).toBe('#')
  })
})
