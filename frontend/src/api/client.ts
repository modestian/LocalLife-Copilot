import axios, { type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'

import type { ApiResponse } from '@/types/api'
import type { TokenPair } from '@/types/auth'

import { toApiClientError } from './errors'
import { tokenStorage } from './token-storage'

declare module 'axios' {
  export interface AxiosRequestConfig {
    skipAuthRefresh?: boolean
  }

  export interface InternalAxiosRequestConfig {
    skipAuthRefresh?: boolean
    authRetryAttempted?: boolean
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const refreshWindowMs = 60_000

let refreshPromise: Promise<TokenPair> | null = null
let authExpiredHandler: (() => void) | undefined

export const apiClient = axios.create({
  baseURL: apiBaseUrl,
  timeout: 15_000,
  headers: { 'Accept-Language': 'zh-CN' },
})

export function setAuthExpiredHandler(handler: () => void): void {
  authExpiredHandler = handler
}

async function refreshSession(): Promise<TokenPair> {
  if (refreshPromise) return refreshPromise

  const session = tokenStorage.get()
  if (!session) throw new Error('No refresh token is available')

  refreshPromise = axios
    .post<ApiResponse<TokenPair>>(
      `${apiBaseUrl}/api/v1/auth/refresh`,
      { refresh_token: session.refresh_token },
      { timeout: 15_000, headers: { 'Accept-Language': 'zh-CN' } },
    )
    .then((response) => {
      tokenStorage.save(response.data.data)
      return response.data.data
    })
    .finally(() => {
      refreshPromise = null
    })

  return refreshPromise
}

function expireSession(): void {
  const hadSession = tokenStorage.get() !== null
  tokenStorage.clear()
  if (hadSession) authExpiredHandler?.()
}

apiClient.interceptors.request.use(async (config) => {
  let session = tokenStorage.get()
  if (
    !config.skipAuthRefresh &&
    session &&
    session.access_expires_at - Date.now() <= refreshWindowMs
  ) {
    try {
      await refreshSession()
      session = tokenStorage.get()
    } catch (error) {
      expireSession()
      throw toApiClientError(error)
    }
  }

  if (!config.skipAuthRefresh && session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`
  }
  config.headers['X-Request-ID'] ??= crypto.randomUUID()
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const config = error.config as InternalAxiosRequestConfig | undefined
      if (
        error.response?.status === 401 &&
        config &&
        !config.skipAuthRefresh &&
        !config.authRetryAttempted
      ) {
        if (!tokenStorage.get()) {
          authExpiredHandler?.()
          throw toApiClientError(error)
        }
        config.authRetryAttempted = true
        try {
          const tokens = await refreshSession()
          config.headers.Authorization = `Bearer ${tokens.access_token}`
          return await apiClient.request(config)
        } catch (refreshError) {
          expireSession()
          throw toApiClientError(refreshError)
        }
      }
    }

    throw toApiClientError(error)
  },
)

export async function requestData<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await apiClient.request<ApiResponse<T>>(config)
  return response.data.data
}
