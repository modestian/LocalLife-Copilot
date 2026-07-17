import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StatusCard from './StatusCard.vue'

describe('StatusCard', () => {
  it.each([
    ['checking', '检查中'],
    ['ready', '运行正常'],
    ['unavailable', '暂不可用'],
  ] as const)('renders the %s state', (state, stateLabel) => {
    const wrapper = mount(StatusCard, {
      props: { label: 'API 服务', state },
    })

    expect(wrapper.text()).toContain('API 服务')
    expect(wrapper.text()).toContain(stateLabel)
    expect(wrapper.attributes('data-state')).toBe(state)
  })
})
