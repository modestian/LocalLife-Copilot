import type { CurrentUser, LoginPayload, TokenPair } from '@/types/auth'

import { requestData } from './client'

export const authApi = {
  login(payload: LoginPayload): Promise<TokenPair> {
    return requestData<TokenPair>({
      method: 'POST',
      url: '/api/v1/auth/login',
      data: payload,
      skipAuthRefresh: true,
    })
  },

  getCurrentUser(): Promise<CurrentUser> {
    return requestData<CurrentUser>({
      method: 'GET',
      url: '/api/v1/users/me',
    })
  },

  logout(refreshToken: string): Promise<null> {
    return requestData<null>({
      method: 'POST',
      url: '/api/v1/auth/logout',
      data: { refresh_token: refreshToken },
      skipAuthRefresh: true,
    })
  },
}
