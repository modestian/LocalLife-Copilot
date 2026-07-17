import { requestData } from './client'

interface WebSocketTokenResponse {
  ws_token?: string
  access_token?: string
  expires_in: number
}

export async function getShortLivedWebSocketToken(): Promise<string> {
  const data = await requestData<WebSocketTokenResponse>({
    method: 'POST',
    url: '/api/v1/auth/ws-token',
  })
  const token = data.ws_token ?? data.access_token
  if (!token) throw new Error('服务端未返回 WebSocket 一次性令牌。')
  return token
}

export function buildWebSocketChatUrl(token: string): string {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || window.location.origin
  const url = new URL('/api/v1/ws/chat', apiBaseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('access_token', token)
  return url.toString()
}
