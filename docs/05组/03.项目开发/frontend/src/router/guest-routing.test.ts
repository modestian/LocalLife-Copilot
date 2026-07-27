import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { tokenStorage } from '@/api/token-storage'

import router from './index'

describe('guest read-only routing', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    tokenStorage.clear()
    await router.replace('/')
  })

  it('allows a guest to browse only the discovery workspace', async () => {
    await router.push('/app')

    expect(router.currentRoute.value.name).toBe('user-home')
    expect(router.currentRoute.value.meta.publicReadOnly).toBe(true)
  })

  it('requires authentication before exposing merchant analytics', async () => {
    await router.push('/merchant')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/merchant')
  })

  it('requires authentication before exposing model management operations', async () => {
    await router.push('/admin/models')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/admin/models')
  })

  it.each([
    '/admin',
    '/admin/knowledge-bases',
    '/admin/knowledge-bases/kb-private',
    '/admin/identity',
  ])('requires authentication before exposing management route %s', async (path) => {
    await router.push('/')
    await router.push(path)

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe(path)
  })
})
