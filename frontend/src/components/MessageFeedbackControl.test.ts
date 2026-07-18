import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError } from '@/api/errors'
import type { FeedbackApi } from '@/types/feedback'

import MessageFeedbackControl from './MessageFeedbackControl.vue'

function createApi(): FeedbackApi {
  return { submit: vi.fn().mockResolvedValue(undefined) }
}

function mountControl(api = createApi()) {
  return mount(MessageFeedbackControl, {
    props: {
      api,
      conversationId: 'conversation-1',
      messageId: 'message-1',
    },
  })
}

describe('MessageFeedbackControl', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('submits a positive rating and shows the submitted state', async () => {
    const api = createApi()
    const wrapper = mountControl(api)

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(api.submit).toHaveBeenCalledWith({
      conversation_id: 'conversation-1',
      message_id: 'message-1',
      rating: 1,
    })
    expect(wrapper.get('[role="status"]').text()).toContain('已记录')
    expect(wrapper.text()).toContain('修改反馈')
  })

  it('requires a reason or correction before submitting negative feedback', async () => {
    const api = createApi()
    const wrapper = mountControl(api)

    await wrapper.get('.message-feedback__negative').trigger('click')
    await wrapper.get('form').trigger('submit')

    expect(api.submit).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('至少选择一个问题原因')
  })

  it('submits selected reasons and a trimmed correction for negative feedback', async () => {
    const api = createApi()
    const wrapper = mountControl(api)

    await wrapper.get('.message-feedback__negative').trigger('click')
    await wrapper.get('input[value="FACT_ERROR"]').setValue(true)
    await wrapper.get('textarea').setValue('  周一闭店，请更新营业时间。  ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.submit).toHaveBeenCalledWith({
      conversation_id: 'conversation-1',
      message_id: 'message-1',
      rating: -1,
      correction: '周一闭店，请更新营业时间。',
      reason_codes: ['FACT_ERROR'],
    })
    expect(wrapper.get('[role="status"]').text()).toContain('反馈已提交')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('keeps the form available and exposes a retryable error when submission fails', async () => {
    const api: FeedbackApi = {
      submit: vi.fn().mockRejectedValue(new ApiClientError({
        status: 503,
        code: 'FEEDBACK_UNAVAILABLE',
        message: '反馈服务暂不可用',
      })),
    }
    const wrapper = mountControl(api)

    await wrapper.get('.message-feedback__negative').trigger('click')
    await wrapper.get('input[value="OUTDATED"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('form').exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('反馈服务暂不可用')
  })
})
