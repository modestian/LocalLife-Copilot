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

  it.each([
    ['/app', 'user-home'],
    ['/merchant', 'merchant-home'],
    ['/admin', 'admin-home'],
    ['/admin/knowledge-bases', 'knowledge-bases'],
    ['/admin/knowledge-bases/kb-public', 'knowledge-base-detail'],
  ])('allows a guest to browse %s without redirecting to login', async (path, routeName) => {
    await router.push(path)

    expect(router.currentRoute.value.name).toBe(routeName)
    expect(router.currentRoute.value.meta.publicReadOnly).toBe(true)
  })
})
