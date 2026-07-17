import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authApi } from '@/api/auth'
import { ApiClientError } from '@/api/errors'
import { tokenStorage } from '@/api/token-storage'
import type { CurrentUser, TokenPair } from '@/types/auth'

import { useAuthStore } from './auth'

vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn(),
    getCurrentUser: vi.fn(),
    logout: vi.fn(),
  },
}))

const tokens: TokenPair = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  token_type: 'bearer',
  expires_in: 1800,
  refresh_expires_in: 604800,
}

const currentUser: CurrentUser = {
  id: 'user-id',
  username: 'ordinary_user',
  display_name: '普通用户',
  email: null,
  department_id: null,
  roles: [{ code: 'USER', name: '普通用户' }],
  permissions: [],
  resource_scopes: [],
}

describe('auth store', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    tokenStorage.clear()
    setActivePinia(createPinia())
  })

  it('restores an existing token session when the store is created', () => {
    tokenStorage.save(tokens)

    const store = useAuthStore()

    expect(store.isAuthenticated).toBe(false)
    expect(store.session?.access_token).toBe('access-token')
  })

  it('loads the current user after login', async () => {
    vi.mocked(authApi.login).mockResolvedValue(tokens)
    vi.mocked(authApi.getCurrentUser).mockResolvedValue(currentUser)
    const store = useAuthStore()

    await expect(store.login({ username: 'ordinary_user', password: 'secret' })).resolves.toEqual(
      currentUser,
    )

    expect(authApi.login).toHaveBeenCalledWith({
      username: 'ordinary_user',
      password: 'secret',
    })
    expect(store.isAuthenticated).toBe(true)
    expect(store.roleCodes).toEqual(['USER'])
    expect(tokenStorage.get()?.refresh_token).toBe('refresh-token')
  })

  it('restores a persisted session by loading users/me', async () => {
    tokenStorage.save(tokens)
    vi.mocked(authApi.getCurrentUser).mockResolvedValue(currentUser)
    const store = useAuthStore()

    await store.initialize()

    expect(authApi.getCurrentUser).toHaveBeenCalledOnce()
    expect(store.currentUser).toEqual(currentUser)
    expect(store.initialized).toBe(true)
  })

  it('keeps Pinia synchronized when refresh rotates the stored tokens', async () => {
    tokenStorage.save(tokens)
    vi.mocked(authApi.getCurrentUser).mockResolvedValue(currentUser)
    const store = useAuthStore()
    await store.initialize()

    tokenStorage.save({
      ...tokens,
      access_token: 'rotated-access-token',
      refresh_token: 'rotated-refresh-token',
    })

    expect(store.session?.access_token).toBe('rotated-access-token')
    expect(store.session?.refresh_token).toBe('rotated-refresh-token')
  })

  it('clears local authentication when users/me rejects the refreshed token', async () => {
    tokenStorage.save(tokens)
    vi.mocked(authApi.getCurrentUser).mockRejectedValue(
      new ApiClientError({
        message: '访问令牌无效或已过期',
        code: 'AUTH_INVALID_ACCESS_TOKEN',
        status: 401,
      }),
    )
    const store = useAuthStore()

    await expect(store.initialize()).rejects.toMatchObject({ code: 'AUTH_INVALID_ACCESS_TOKEN' })

    expect(store.currentUser).toBeNull()
    expect(tokenStorage.get()).toBeNull()
  })

  it('preserves tokens and allows retry after a transient users/me failure', async () => {
    tokenStorage.save(tokens)
    vi.mocked(authApi.getCurrentUser)
      .mockRejectedValueOnce(
        new ApiClientError({ message: '网络连接失败，请检查网络', code: 'NETWORK_ERROR' }),
      )
      .mockResolvedValueOnce(currentUser)
    const store = useAuthStore()

    await expect(store.initialize()).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
    expect(tokenStorage.get()).not.toBeNull()
    expect(store.initialized).toBe(false)

    await store.initialize()
    expect(store.currentUser).toEqual(currentUser)
    expect(authApi.getCurrentUser).toHaveBeenCalledTimes(2)
  })

  it('clears local state even when the logout request fails', async () => {
    tokenStorage.save(tokens)
    vi.mocked(authApi.logout).mockRejectedValue(new Error('network unavailable'))
    const store = useAuthStore()

    await expect(store.logout()).resolves.toBeUndefined()

    expect(authApi.logout).toHaveBeenCalledWith('refresh-token')
    expect(store.isAuthenticated).toBe(false)
    expect(tokenStorage.get()).toBeNull()
    expect(store.lastError).toMatchObject({
      code: 'UNKNOWN_ERROR',
      message: '发生未知错误，请稍后重试',
    })
  })

  it('clears the session without calling logout when no refresh token exists', () => {
    const store = useAuthStore()

    store.clearSession()

    expect(authApi.logout).not.toHaveBeenCalled()
    expect(store.session).toBeNull()
  })
})
