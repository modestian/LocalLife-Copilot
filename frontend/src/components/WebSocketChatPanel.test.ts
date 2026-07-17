import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WebSocketChatPanel from './WebSocketChatPanel.vue'

describe('WebSocketChatPanel read-only mode', () => {
  it('does not render conversation write controls for guests', () => {
    const wrapper = mount(WebSocketChatPanel, {
      props: { readOnly: true },
    })

    expect(wrapper.text()).toContain('当前为只读浏览')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.find('textarea').exists()).toBe(false)
  })
})
