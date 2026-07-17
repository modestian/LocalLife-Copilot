export interface LoginPayload {
  username: string
  password: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  refresh_expires_in: number
}

export interface TokenSession extends TokenPair {
  access_expires_at: number
  refresh_expires_at: number
}

export interface UserRole {
  code: string
  name: string
}

export interface CurrentUser {
  id: string
  username: string
  display_name?: string
  roles: UserRole[]
}
