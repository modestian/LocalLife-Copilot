import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ChatFeedbackControls from './ChatFeedbackControls.vue'

const ids = {
  conversationId: '0190c4d2-7f20-7b31-9f75-8f6cc8e2b120',
  messageId: '0190c4d2-7f20-7b31-9f75-8f6cc8e2b121',
}

describe('ChatFeedbackControls', () => {
  it('submits a positive feedback entry immediately and shows success', async () => {
    const submitFeedback = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(ChatFeedbackControls, { props: { ...ids, submitFeedback } })

    await wrapper.get('button[aria-pressed="false"]').trigger('click')

    expect(submitFeedback).toHaveBeenCalledWith({
      conversation_id: ids.conversationId,
      message_id: ids.messageId,
      rating: 1,
      reason_codes: [],
    })
    expect(wrapper.text()).toContain('已成功记录')
  })

  it('requires a reason or correction before submitting negative feedback', async () => {
    const submitFeedback = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(ChatFeedbackControls, { props: { ...ids, submitFeedback } })

    await wrapper.findAll('button[aria-pressed="false"]')[1].trigger('click')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.text()).toContain('请选择原因')
    expect(submitFeedback).not.toHaveBeenCalled()

    await wrapper.get('input[value="OUTDATED"]').setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(submitFeedback).toHaveBeenCalledWith({
      conversation_id: ids.conversationId,
      message_id: ids.messageId,
      rating: -1,
      reason_codes: ['OUTDATED'],
    })
  })

  it('shows an actionable failure state when submission fails', async () => {
    const submitFeedback = vi.fn().mockRejectedValue(new Error('服务暂不可用'))
    const wrapper = mount(ChatFeedbackControls, { props: { ...ids, submitFeedback } })

    await wrapper.get('button[aria-pressed="false"]').trigger('click')

    expect(wrapper.text()).toContain('提交失败：服务暂不可用')
    expect(wrapper.get('[role="alert"]').text()).toContain('重试')
  })
})
