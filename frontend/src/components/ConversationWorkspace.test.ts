import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type {
  ChatMessage,
  ConversationApi,
  ConversationSummary,
} from '@/api/conversations'

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

describe('ConversationWorkspace', () => {
  it('starts a scene conversation with composite exploration conditions', async () => {
    const api = createApi()
    const wrapper = mount(ConversationWorkspace, { props: { api } })
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
    expect(api.sendMessage).toHaveBeenCalledWith(
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
    const wrapper = mount(ConversationWorkspace, {
      props: { api, initialConversations: [conversation] },
    })

    await wrapper.get('[data-conversation-id="conversation-history"]').trigger('click')
    await wrapper.get('textarea').setValue('把预算限制在人均 80 元以内')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('我找到两家适合聚会的川菜馆')
    expect(api.createConversation).not.toHaveBeenCalled()
    expect(api.sendMessage).toHaveBeenCalledWith(
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

  it('keeps the draft and removes the optimistic message when sending fails', async () => {
    const api = createApi({
      sendMessage: vi.fn().mockRejectedValue(new Error('网络暂时不可用')),
    })
    const wrapper = mount(ConversationWorkspace, { props: { api } })
    await flushPromises()

    await wrapper.get('textarea').setValue('推荐一家附近的面馆')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('textarea').element.value).toBe('推荐一家附近的面馆')
    expect(wrapper.text()).toContain('网络暂时不可用')
    expect(wrapper.findAll('.chat-message')).toHaveLength(0)
  })
})
