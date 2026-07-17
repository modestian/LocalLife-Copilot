import axios, { type AxiosAdapter, AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiResponse } from '@/types/api'
import type { TokenPair } from '@/types/auth'

import { apiClient } from './client'
import { tokenStorage } from './token-storage'

const expiredTokens: TokenPair = {
  access_token: 'expired-access-token',
  refresh_token: 'refresh-token',
  token_type: 'bearer',
  expires_in: 0,
  refresh_expires_in: 3600,
}

const refreshedTokens: TokenPair = {
  access_token: 'fresh-access-token',
  refresh_token: 'rotated-refresh-token',
  token_type: 'bearer',
  expires_in: 1800,
  refresh_expires_in: 604800,
}

describe('apiClient authentication', () => {
  beforeEach(() => tokenStorage.clear())

  afterEach(() => {
    vi.restoreAllMocks()
    tokenStorage.clear()
  })

  it('persists token expiry timestamps', () => {
    const beforeSave = Date.now()
    const session = tokenStorage.save(refreshedTokens)

    expect(session.access_expires_at).toBeGreaterThanOrEqual(beforeSave + 1_800_000)
    expect(tokenStorage.get()?.refresh_token).toBe('rotated-refresh-token')
  })

  it('shares one proactive refresh across concurrent requests', async () => {
    tokenStorage.save(expiredTokens)
    const refreshResponse: ApiResponse<TokenPair> = {
      code: 'OK',
      message: 'success',
      data: refreshedTokens,
      request_id: 'refresh-request-id',
    }
    const refreshSpy = vi.spyOn(axios, 'post').mockResolvedValue({ data: refreshResponse })
    const authorizationHeaders: string[] = []
    const adapter: AxiosAdapter = async (config) => {
      authorizationHeaders.push(String(config.headers.Authorization))
      return {
        data: { code: 'OK', message: 'success', data: {}, request_id: 'request-id' },
        status: 200,
        statusText: 'OK',
        headers: new AxiosHeaders(),
        config,
      }
    }

    await Promise.all([
      apiClient.get('/api/v1/protected-a', { adapter }),
      apiClient.get('/api/v1/protected-b', { adapter }),
    ])

    expect(refreshSpy).toHaveBeenCalledOnce()
    expect(authorizationHeaders).toEqual(['Bearer fresh-access-token', 'Bearer fresh-access-token'])
  })
})
