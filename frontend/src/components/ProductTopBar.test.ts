import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import type { CurrentUser, TokenSession } from '@/types/auth'

import ProductTopBar from './ProductTopBar.vue'

function userWithRole(code: string): CurrentUser {
  return {
    id: `${code.toLowerCase()}-id`,
    username: code.toLowerCase(),
    display_name: code,
    email: null,
    department_id: null,
    roles: [{ code, name: code }],
    permissions: [],
    resource_scopes: [],
  }
}

const session: TokenSession = {
  access_token: 'access',
  refresh_token: 'refresh',
  token_type: 'bearer',
  expires_in: 3600,
  refresh_expires_in: 7200,
  access_expires_at: Date.now() + 3_600_000,
  refresh_expires_at: Date.now() + 7_200_000,
}

async function mountTopBar(role?: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore()
  if (role) {
    store.session = session
    store.currentUser = userWithRole(role)
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'root', component: { template: '<div />' } },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/app', component: { template: '<div />' } },
      { path: '/merchant', component: { template: '<div />' } },
      { path: '/admin', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  return mount(ProductTopBar, { global: { plugins: [pinia, router] } })
}

describe('ProductTopBar role navigation', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it.each([undefined, 'USER'])('shows only discovery for %s', async (role) => {
    const wrapper = await mountTopBar(role)

    expect(wrapper.findAll('nav a').map((link) => link.text())).toEqual(['探店'])
  })

  it('shows only the merchant workspace to merchants', async () => {
    const wrapper = await mountTopBar('MERCHANT_ADMIN')

    expect(wrapper.findAll('nav a').map((link) => link.text())).toEqual(['商家板块'])
  })

  it('shows only the management workspace to platform administrators', async () => {
    const wrapper = await mountTopBar('PLATFORM_ADMIN')

    expect(wrapper.findAll('nav a').map((link) => link.text())).toEqual(['管理板块'])
  })
})
