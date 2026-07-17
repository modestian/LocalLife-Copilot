import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import { tokenStorage } from '@/api/token-storage'
import type { LoginPayload, TokenSession } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const session = ref<TokenSession | null>(tokenStorage.get())
  const isAuthenticated = computed(() => session.value !== null)

  async function login(payload: LoginPayload): Promise<void> {
    const tokens = await authApi.login(payload)
    session.value = tokenStorage.save(tokens)
  }

  async function logout(): Promise<void> {
    const refreshToken = session.value?.refresh_token
    try {
      if (refreshToken) await authApi.logout(refreshToken)
    } finally {
      clearSession()
    }
  }

  function clearSession(): void {
    tokenStorage.clear()
    session.value = null
  }

  return { session, isAuthenticated, login, logout, clearSession }
})
