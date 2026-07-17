import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import type {
  ChatMessage,
  ConversationApi,
  ConversationSummary,
} from '@/api/conversations'
import type {
  WebSocketChatController,
  WebSocketChatState,
} from '@/composables/useWebSocketChat'
import type {
  MerchantRecommendation,
  RecommendationSource,
} from '@/types/recommendation'

import ConversationWorkspace from './ConversationWorkspace.vue'

const now = '2026-07-17T05:00:00Z'

function createApi(overrides: Partial<ConversationApi> = {}): ConversationApi {
  return {
    listConversations: vi.fn().mockResolvedValue([]),
    createConversation: vi.fn().mockResolvedValue({
      id: 'conversation-new',
      title: '学习办公咖啡馆',
      scenario: 'study',
      status: 'ACTIVE',
      updated_at: now,
      message_count: 0,
    }),
    listMessages: vi.fn().mockResolvedValue([]),
    sendMessage: vi.fn().mockResolvedValue({
      id: 'assistant-new',
      conversation_id: 'conversation-new',
      role: 'ASSISTANT',
      content: '可以看看三公里内有插座且工作日下午较安静的咖啡馆。',
      status: 'COMPLETED',
      created_at: now,
    }),
    ...overrides,
  }
}

interface StreamResult {
  content?: string
  error?: string
  recommendations?: MerchantRecommendation[]
  sources?: RecommendationSource[]
}

function createStream(result: StreamResult = {}): WebSocketChatController {
  const state = ref<WebSocketChatState>('idle')
  const content = ref('')
  const sources = ref<RecommendationSource[]>([])
  const recommendations = ref<MerchantRecommendation[]>([])
  const fallback = ref({ triggered: false })
  const errorMessage = ref('')
  const reconnectAttempt = ref(0)
  const requestId = ref<string | null>(null)
  const messageId = ref<string | null>(null)
  const send = vi.fn(async () => {
    state.value = 'streaming'
    content.value = result.content ?? ''
    sources.value = result.sources ?? []
    recommendations.value = result.recommendations ?? []
    if (result.error) {
      errorMessage.value = result.error
      state.value = 'error'
      return
    }
    messageId.value = 'assistant-streamed'
    state.value = 'completed'
  })
  const cancel = vi.fn(() => { state.value = 'cancelled' })
  const retry = vi.fn(async () => { state.value = 'streaming' })
  const disconnect = vi.fn()

  return {
    state,
    content,
    sources,
    recommendations,
    fallback,
    errorMessage,
    reconnectAttempt,
    requestId,
    messageId,
    send,
    cancel,
    retry,
    disconnect,
  }
}

describe('ConversationWorkspace', () => {
  it('keeps all persistent conversation controls unavailable to guests', async () => {
    const api = createApi()
    const stream = createStream()
    const wrapper = mount(ConversationWorkspace, {
      props: { api, stream, readOnly: true },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('当前为只读浏览')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('＋ 新对话')
    expect(api.listConversations).not.toHaveBeenCalled()
    expect(api.createConversation).not.toHaveBeenCalled()
    expect(stream.send).not.toHaveBeenCalled()
  })

  it('starts a scene conversation with composite exploration conditions', async () => {
    const api = createApi()
    const stream = createStream({
      content: '可以看看三公里内有插座且工作日下午较安静的咖啡馆。',
    })
    const wrapper = mount(ConversationWorkspace, { props: { api, stream } })
    await flushPromises()

    await wrapper.get('[data-scenario="study"]').trigger('click')
    await wrapper.get('input[placeholder="元/人"]').setValue(60)
    await wrapper.get('input[placeholder="川菜、咖啡…"]').setValue('咖啡')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.createConversation).toHaveBeenCalledWith(expect.objectContaining({
      scenario: 'study',
      constraints: expect.objectContaining({ budget_yuan: 60, cuisine: '咖啡' }),
    }))
    expect(stream.send).toHaveBeenCalledWith(
      'conversation-new',
      expect.stringContaining('场景：学习办公；距离：3 公里内；预算：人均 60 元以内；菜系/品类：咖啡'),
    )
    expect(wrapper.text()).toContain('适合学习办公')
    expect(wrapper.text()).toContain('三公里内有插座')
  })

  it('restores an existing conversation and sends a multi-turn follow-up', async () => {
    const history: ChatMessage[] = [
      {
        id: 'message-user-1',
        conversation_id: 'conversation-history',
        role: 'USER',
        content: '附近有什么适合聚会的川菜馆？',
        status: 'COMPLETED',
        created_at: now,
      },
      {
        id: 'message-assistant-1',
        conversation_id: 'conversation-history',
        role: 'ASSISTANT',
        content: '我找到两家适合聚会的川菜馆。',
        status: 'COMPLETED',
        created_at: now,
      },
    ]
    const conversation: ConversationSummary = {
      id: 'conversation-history',
      title: '朋友聚会川菜馆',
      scenario: 'gathering',
      status: 'ACTIVE',
      updated_at: now,
      message_count: 2,
      preview_messages: history,
    }
    const api = createApi({
      sendMessage: vi.fn().mockResolvedValue({
        id: 'message-assistant-2',
        conversation_id: 'conversation-history',
        role: 'ASSISTANT',
        content: '可以，已缩小到人均 80 元以内。',
        status: 'COMPLETED',
        created_at: now,
      }),
    })
    const stream = createStream({ content: '可以，已缩小到人均 80 元以内。' })
    const wrapper = mount(ConversationWorkspace, {
      props: { api, stream, initialConversations: [conversation] },
    })

    await wrapper.get('[data-conversation-id="conversation-history"]').trigger('click')
    await wrapper.get('textarea').setValue('把预算限制在人均 80 元以内')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('我找到两家适合聚会的川菜馆')
    expect(api.createConversation).not.toHaveBeenCalled()
    expect(stream.send).toHaveBeenCalledWith(
      'conversation-history',
      expect.stringContaining('把预算限制在人均 80 元以内'),
    )
    expect(wrapper.text()).toContain('已缩小到人均 80 元以内')
  })

  it('loads messages when a server conversation is selected', async () => {
    const conversation: ConversationSummary = {
      id: 'conversation-server',
      title: '约会餐厅',
      status: 'ACTIVE',
      updated_at: now,
      message_count: 1,
    }
    const api = createApi({
      listConversations: vi.fn().mockResolvedValue([conversation]),
      listMessages: vi.fn().mockResolvedValue([{
        id: 'server-message',
        conversation_id: 'conversation-server',
        role: 'ASSISTANT',
        content: '这是从服务端恢复的历史消息。',
        status: 'COMPLETED',
        created_at: now,
      }]),
    })
    const wrapper = mount(ConversationWorkspace, { props: { api } })
    await flushPromises()

    await wrapper.get('[data-conversation-id="conversation-server"]').trigger('click')
    await flushPromises()

    expect(api.listMessages).toHaveBeenCalledWith('conversation-server')
    expect(wrapper.text()).toContain('这是从服务端恢复的历史消息')
  })

  it('keeps the failed answer visible with an actionable retry state', async () => {
    const api = createApi()
    const stream = createStream({ error: '网络暂时不可用' })
    const wrapper = mount(ConversationWorkspace, { props: { api, stream } })
    await flushPromises()

    await wrapper.get('textarea').setValue('推荐一家附近的面馆')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('textarea').element.value).toBe('')
    expect(wrapper.text()).toContain('网络暂时不可用')
    expect(wrapper.findAll('.chat-message')).toHaveLength(2)
    expect(wrapper.text()).toContain('生成失败')
    expect(wrapper.text()).toContain('重试回答')
  })

  it('renders streamed recommendations and opens their highlighted citations', async () => {
    const source: RecommendationSource = {
      chunk_id: 'chunk-1',
      source_location: '点评 / 星光咖啡',
      source_url: '/app/reviews/review-1#chunk-1',
      content: '靠窗位置安静，而且每张桌子附近都有插座。',
      highlight_text: '靠窗位置安静',
      score: 0.92,
    }
    const recommendation: MerchantRecommendation = {
      merchant_id: 'merchant-1',
      name: '星光咖啡',
      category: '咖啡馆',
      reason: '安静且有插座，适合学习。',
      distance_meter: 850,
      avg_price_cent: 5800,
      data_updated_at: now,
      source_chunk_ids: ['chunk-1'],
    }
    const stream = createStream({
      content: '**星光咖啡**比较符合当前条件。',
      recommendations: [recommendation],
      sources: [source],
    })
    const wrapper = mount(ConversationWorkspace, {
      props: { api: createApi(), stream },
    })
    await flushPromises()

    await wrapper.get('textarea').setValue('找一家安静的咖啡馆')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('.safe-markdown strong').text()).toBe('星光咖啡')
    expect(wrapper.text()).toContain('850 米')
    await wrapper.get('.recommendation-card__sources').trigger('click')
    expect(wrapper.get('[role="dialog"] mark').text()).toBe('靠窗位置安静')
    expect(wrapper.get('[role="dialog"] a').attributes('href')).toBe('/app/reviews/review-1#chunk-1')
  })
})
