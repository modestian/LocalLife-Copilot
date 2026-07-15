import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusCard from './StatusCard.vue'

describe('StatusCard', () => {
  it('renders the ready state', () => {
    const wrapper = mount(StatusCard, {
      props: { label: 'API 服务', state: 'ready' },
    })

    expect(wrapper.text()).toContain('API 服务')
    expect(wrapper.text()).toContain('运行正常')
    expect(wrapper.attributes('data-state')).toBe('ready')
  })
})

