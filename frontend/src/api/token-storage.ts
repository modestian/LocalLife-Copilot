import type { TokenPair, TokenSession } from '@/types/auth'

const STORAGE_KEY = 'local-life-copilot.auth-session'

let memorySession: TokenSession | null = readStoredSession()
const listeners = new Set<(session: TokenSession | null) => void>()

function isTokenSession(value: unknown): value is TokenSession {
  if (!value || typeof value !== 'object') return false
  const session = value as Partial<TokenSession>
  return (
    typeof session.access_token === 'string' &&
    typeof session.refresh_token === 'string' &&
    typeof session.access_expires_at === 'number' &&
    typeof session.refresh_expires_at === 'number'
  )
}

function readStoredSession(): TokenSession | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (!value) return null
    const session: unknown = JSON.parse(value)
    if (!isTokenSession(session) || session.refresh_expires_at <= Date.now()) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return session
  } catch {
    return null
  }
}

function persist(session: TokenSession | null): void {
  memorySession = session
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Memory storage still allows the current tab to continue.
  }
  listeners.forEach((listener) => listener(session))
}

export const tokenStorage = {
  get(): TokenSession | null {
    if (memorySession?.refresh_expires_at && memorySession.refresh_expires_at <= Date.now()) {
      persist(null)
    }
    return memorySession
  },

  save(tokens: TokenPair): TokenSession {
    const now = Date.now()
    const session: TokenSession = {
      ...tokens,
      access_expires_at: now + tokens.expires_in * 1000,
      refresh_expires_at: now + tokens.refresh_expires_in * 1000,
    }
    persist(session)
    return session
  },

  clear(): void {
    persist(null)
  },

  subscribe(listener: (session: TokenSession | null) => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}
