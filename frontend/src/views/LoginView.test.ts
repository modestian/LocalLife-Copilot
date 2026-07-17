/* eslint-disable vue/one-component-per-file -- inline stubs keep this component test isolated */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'
import { ElMessage } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError } from '@/api/errors'
import { tokenStorage } from '@/api/token-storage'
import { useAuthStore } from '@/stores/auth'

import LoginView from './LoginView.vue'

const FormStub = defineComponent({
  emits: ['submit'],
  setup(_props, { emit, expose }) {
    expose({ validate: () => Promise.resolve(true) })
    return { emit }
  },
  template: '<form @submit.prevent="emit(\'submit\', $event)"><slot /></form>',
})

const InputStub = defineComponent({
  props: {
    modelValue: { type: String, default: '' },
    type: { type: String, default: 'text' },
    placeholder: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  template: `
    <input
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', $event.target.value)"
    >
  `,
})

const ButtonStub = defineComponent({
  props: {
    nativeType: { type: String, default: 'button' },
    loading: { type: Boolean, default: false },
  },
  template: '<button :type="nativeType" :data-loading="loading"><slot /></button>',
})

async function mountLogin(redirect = '/') {
  const pinia = createPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginView },
      { path: '/', component: { template: '<div>home</div>' } },
      { path: '/conversations', component: { template: '<div>conversations</div>' } },
    ],
  })
  await router.push({ path: '/login', query: { redirect } })
  await router.isReady()
  const wrapper = mount(LoginView, {
    global: {
      plugins: [pinia, router],
      stubs: {
        ElCard: { template: '<section><slot name="header" /><slot /></section>' },
        ElForm: FormStub,
        ElFormItem: { template: '<label><slot /></label>' },
        ElInput: InputStub,
        ElButton: ButtonStub,
      },
    },
  })
  return { wrapper, router, store: useAuthStore(pinia) }
}

afterEach(() => {
  vi.restoreAllMocks()
  tokenStorage.clear()
})

describe('LoginView', () => {
  it('submits credentials and returns to the requested route', async () => {
    const { wrapper, router, store } = await mountLogin('/conversations')
    const login = vi.spyOn(store, 'login').mockResolvedValue(undefined)

    await wrapper.get('input[placeholder="请输入账号"]').setValue('demo-user')
    await wrapper.get('input[placeholder="请输入密码"]').setValue('correct-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(login).toHaveBeenCalledWith({
      username: 'demo-user',
      password: 'correct-password',
    })
    expect(router.currentRoute.value.fullPath).toBe('/conversations')
  })

  it('shows the API error and releases the loading state after a failed login', async () => {
    const { wrapper, store } = await mountLogin()
    vi.spyOn(store, 'login').mockRejectedValue(new ApiClientError({
      code: 'AUTH_INVALID_CREDENTIALS',
      message: '账号或密码错误',
      status: 401,
    }))
    const message = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)

    await wrapper.get('input[placeholder="请输入账号"]').setValue('demo-user')
    await wrapper.get('input[placeholder="请输入密码"]').setValue('wrong-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(message).toHaveBeenCalledWith('账号或密码错误')
    expect(wrapper.get('button').attributes('data-loading')).toBe('false')
  })
})
