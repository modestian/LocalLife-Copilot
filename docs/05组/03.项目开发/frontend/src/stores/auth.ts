import { computed, onScopeDispose, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import { ApiClientError, isAuthenticationError, toApiClientError } from '@/api/errors'
import { tokenStorage } from '@/api/token-storage'
import type { CurrentUser, LoginPayload, TokenSession } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const session = ref<TokenSession | null>(tokenStorage.get())
  const currentUser = ref<CurrentUser | null>(null)
  const initialized = ref(false)
  const lastError = ref<ApiClientError | null>(null)
  let initializationPromise: Promise<void> | null = null

  const isAuthenticated = computed(() => session.value !== null && currentUser.value !== null)
  const roleCodes = computed(() => currentUser.value?.roles.map((role) => role.code) ?? [])

  const unsubscribe = tokenStorage.subscribe((nextSession) => {
    session.value = nextSession
    if (!nextSession) currentUser.value = null
  })
  onScopeDispose(unsubscribe)

  async function initialize(force = false): Promise<void> {
    if (initialized.value && !force) return
    if (initializationPromise) return initializationPromise
    if (!tokenStorage.get()) {
      clearSession()
      return
    }

    initialized.value = false
    lastError.value = null
    initializationPromise = authApi
      .getCurrentUser()
      .then((user) => {
        currentUser.value = user
        initialized.value = true
      })
      .catch((error: unknown) => {
        const apiError = toApiClientError(error)
        lastError.value = apiError
        if (isAuthenticationError(apiError)) clearSession()
        else initialized.value = false
        throw apiError
      })
      .finally(() => {
        initializationPromise = null
      })

    return initializationPromise
  }

  async function login(payload: LoginPayload): Promise<CurrentUser> {
    lastError.value = null
    initialized.value = false
    try {
      const tokens = await authApi.login(payload)
      tokenStorage.save(tokens)
      await initialize(true)
      if (!currentUser.value) throw new Error('Current user is unavailable after login')
      return currentUser.value
    } catch (error) {
      lastError.value = toApiClientError(error)
      clearSession()
      throw lastError.value
    }
  }

  async function logout(): Promise<void> {
    const refreshToken = tokenStorage.get()?.refresh_token
    try {
      if (refreshToken) await authApi.logout(refreshToken)
    } catch (error) {
      lastError.value = toApiClientError(error)
    } finally {
      clearSession()
    }
  }

  function clearSession(): void {
    tokenStorage.clear()
    session.value = null
    currentUser.value = null
    initialized.value = true
    localStorage.removeItem('local-life-copilot.merchant-uid')
  }

  return {
    session,
    currentUser,
    initialized,
    lastError,
    isAuthenticated,
    roleCodes,
    initialize,
    login,
    logout,
    clearSession,
  }
})
