import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/auth'
import { tokenStorage } from '@/api/token-storage'
import type { TokenPair } from '@/types/auth'

import { useAuthStore } from './auth'

const tokens: TokenPair = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  token_type: 'bearer',
  expires_in: 1800,
  refresh_expires_in: 604800,
}

describe('useAuthStore', () => {
  beforeEach(() => {
    tokenStorage.clear()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    tokenStorage.clear()
  })

  it('restores an existing valid session when the store is created', () => {
    tokenStorage.save(tokens)

    const store = useAuthStore()

    expect(store.isAuthenticated).toBe(true)
    expect(store.session?.access_token).toBe('access-token')
  })

  it('persists the token session after login', async () => {
    vi.spyOn(authApi, 'login').mockResolvedValue(tokens)
    const store = useAuthStore()

    await store.login({ username: 'demo-user', password: 'correct-password' })

    expect(authApi.login).toHaveBeenCalledWith({
      username: 'demo-user',
      password: 'correct-password',
    })
    expect(store.isAuthenticated).toBe(true)
    expect(tokenStorage.get()?.refresh_token).toBe('refresh-token')
  })

  it('clears local state even when the logout request fails', async () => {
    tokenStorage.save(tokens)
    setActivePinia(createPinia())
    const store = useAuthStore()
    vi.spyOn(authApi, 'logout').mockRejectedValue(new Error('network unavailable'))

    await expect(store.logout()).rejects.toThrow('network unavailable')

    expect(authApi.logout).toHaveBeenCalledWith('refresh-token')
    expect(store.isAuthenticated).toBe(false)
    expect(tokenStorage.get()).toBeNull()
  })

  it('clears the session without calling logout when no refresh token exists', () => {
    const store = useAuthStore()
    const logoutSpy = vi.spyOn(authApi, 'logout')

    store.clearSession()

    expect(logoutSpy).not.toHaveBeenCalled()
    expect(store.session).toBeNull()
  })
})
