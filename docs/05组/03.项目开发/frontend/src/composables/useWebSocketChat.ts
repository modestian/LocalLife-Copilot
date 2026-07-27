import { onBeforeUnmount, ref } from 'vue'

import {
  buildWebSocketChatUrl,
  getShortLivedWebSocketToken,
} from '@/api/websocket-chat'
import type {
  MerchantRecommendation,
  RecommendationFallback,
  RecommendationSource,
} from '@/types/recommendation'

export type WebSocketChatState =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'reconnecting'
  | 'completed'
  | 'cancelled'
  | 'error'

export type ChatSource = RecommendationSource

interface ActiveRequest {
  type: 'chat.request'
  request_id: string
  conversation_id: string
  content: string
  options: { knowledge_base_ids: string[] }
}

interface ChatSocket {
  readonly readyState: number
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent<string>) => void) | null
  onerror: ((event: Event) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export interface UseWebSocketChatOptions {
  getToken?: () => Promise<string>
  buildUrl?: (token: string) => string
  createSocket?: (url: string) => ChatSocket
  heartbeatTimeoutMs?: number
  reconnectBaseDelayMs?: number
  maxReconnectAttempts?: number
  renderBufferMs?: number
}

const SOCKET_OPEN = 1

export function useWebSocketChat(options: UseWebSocketChatOptions = {}) {
  const state = ref<WebSocketChatState>('idle')
  const content = ref('')
  const sources = ref<ChatSource[]>([])
  const recommendations = ref<MerchantRecommendation[]>([])
  const fallback = ref<RecommendationFallback>({ triggered: false })
  const errorMessage = ref('')
  const reconnectAttempt = ref(0)
  const requestId = ref<string | null>(null)
  const messageId = ref<string | null>(null)

  const getToken = options.getToken ?? getShortLivedWebSocketToken
  const buildUrl = options.buildUrl ?? buildWebSocketChatUrl
  const createSocket = options.createSocket ?? ((url: string) => new WebSocket(url))
  const heartbeatTimeoutMs = options.heartbeatTimeoutMs ?? 45_000
  const reconnectBaseDelayMs = options.reconnectBaseDelayMs ?? 600
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 3
  const renderBufferMs = options.renderBufferMs ?? 32

  let socket: ChatSocket | null = null
  let activeRequest: ActiveRequest | null = null
  let connectionPromise: Promise<void> | null = null
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let renderTimer: ReturnType<typeof setTimeout> | null = null
  let pendingDelta = ''
  let intentionalClose = false

  function clearTimer(timer: ReturnType<typeof setTimeout> | null): void {
    if (timer) clearTimeout(timer)
  }

  function flushPendingDelta(): void {
    clearTimer(renderTimer)
    renderTimer = null
    if (!pendingDelta) return
    content.value += pendingDelta
    pendingDelta = ''
  }

  function scheduleDeltaFlush(): void {
    if (renderTimer) return
    renderTimer = setTimeout(flushPendingDelta, renderBufferMs)
  }

  function armHeartbeatTimeout(): void {
    clearTimer(heartbeatTimer)
    heartbeatTimer = setTimeout(() => {
      errorMessage.value = '连接心跳超时，正在尝试恢复本次回答。'
      socket?.close(4000, 'heartbeat timeout')
    }, heartbeatTimeoutMs)
  }

  function stopHeartbeatTimeout(): void {
    clearTimer(heartbeatTimer)
    heartbeatTimer = null
  }

  function transmitActiveRequest(): void {
    if (!activeRequest || socket?.readyState !== SOCKET_OPEN) return
    socket.send(JSON.stringify(activeRequest))
    state.value = 'streaming'
    armHeartbeatTimeout()
  }

  function handleServerMessage(event: MessageEvent<string>): void {
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(event.data) as Record<string, unknown>
    } catch {
      state.value = 'error'
      errorMessage.value = '收到无法解析的流式事件，请重试本次回答。'
      return
    }

    const type = String(payload.type ?? '')
    if (type === 'ping') {
      if (socket?.readyState === SOCKET_OPEN) socket.send(JSON.stringify({ type: 'pong' }))
      armHeartbeatTimeout()
      return
    }
    if (type === 'chat.delta') {
      pendingDelta += String(payload.delta ?? payload.content ?? '')
      scheduleDeltaFlush()
      return
    }
    if (type === 'chat.sources') {
      sources.value = Array.isArray(payload.sources) ? payload.sources as ChatSource[] : []
      if (Array.isArray(payload.recommendations)) {
        recommendations.value = payload.recommendations as MerchantRecommendation[]
      }
      if (payload.fallback && typeof payload.fallback === 'object') {
        fallback.value = payload.fallback as RecommendationFallback
      }
      return
    }
    if (type === 'chat.recommendations') {
      recommendations.value = Array.isArray(payload.recommendations)
        ? payload.recommendations as MerchantRecommendation[]
        : []
      fallback.value = payload.fallback && typeof payload.fallback === 'object'
        ? payload.fallback as RecommendationFallback
        : { triggered: recommendations.value.length === 0 }
      return
    }
    if (type === 'chat.completed') {
      flushPendingDelta()
      stopHeartbeatTimeout()
      state.value = 'completed'
      errorMessage.value = ''
      reconnectAttempt.value = 0
      messageId.value = typeof payload.message_id === 'string' ? payload.message_id : null
      activeRequest = null
      return
    }
    if (type === 'chat.error') {
      flushPendingDelta()
      stopHeartbeatTimeout()
      state.value = 'error'
      errorMessage.value = String(payload.message ?? '回答生成失败，请重试。')
    }
  }

  async function connect(): Promise<void> {
    if (socket?.readyState === SOCKET_OPEN) return
    if (connectionPromise) return connectionPromise

    state.value = reconnectAttempt.value > 0 ? 'reconnecting' : 'connecting'
    connectionPromise = (async () => {
      const token = await getToken()
      await new Promise<void>((resolve, reject) => {
        const nextSocket = createSocket(buildUrl(token))
        socket = nextSocket
        intentionalClose = false
        let opened = false

        nextSocket.onopen = () => {
          opened = true
          armHeartbeatTimeout()
          resolve()
        }
        nextSocket.onmessage = handleServerMessage
        nextSocket.onerror = () => {
          if (!opened) reject(new Error('WebSocket 连接失败，请检查网络。'))
        }
        nextSocket.onclose = () => {
          stopHeartbeatTimeout()
          if (!opened) reject(new Error('WebSocket 在建立连接前已关闭。'))
          if (
            !intentionalClose
            && opened
            && activeRequest
            && ['connecting', 'streaming', 'reconnecting'].includes(state.value)
          ) {
            scheduleReconnect(errorMessage.value || '连接已中断，正在恢复本次回答。')
          }
        }
      })
    })()

    try {
      await connectionPromise
    } finally {
      connectionPromise = null
    }
  }

  function scheduleReconnect(reason: string): void {
    clearTimer(reconnectTimer)
    if (reconnectAttempt.value >= maxReconnectAttempts) {
      state.value = 'error'
      errorMessage.value = `${reason} 已达到最大重连次数，请手动重试。`
      return
    }

    reconnectAttempt.value += 1
    state.value = 'reconnecting'
    errorMessage.value = `${reason} 第 ${reconnectAttempt.value} 次重连中…`
    const delay = reconnectBaseDelayMs * 2 ** (reconnectAttempt.value - 1)
    reconnectTimer = setTimeout(async () => {
      try {
        await connect()
        transmitActiveRequest()
      } catch (error: unknown) {
        scheduleReconnect(error instanceof Error ? error.message : '重连失败。')
      }
    }, delay)
  }

  async function send(
    conversationId: string,
    message: string,
    knowledgeBaseIds: string[] = [],
  ): Promise<void> {
    content.value = ''
    sources.value = []
    recommendations.value = []
    fallback.value = { triggered: false }
    errorMessage.value = ''
    pendingDelta = ''
    reconnectAttempt.value = 0
    messageId.value = null
    activeRequest = {
      type: 'chat.request',
      request_id: crypto.randomUUID(),
      conversation_id: conversationId,
      content: message,
      options: { knowledge_base_ids: knowledgeBaseIds },
    }
    requestId.value = activeRequest.request_id

    try {
      await connect()
      transmitActiveRequest()
    } catch (error: unknown) {
      state.value = 'error'
      errorMessage.value = error instanceof Error ? error.message : 'WebSocket 连接失败。'
    }
  }

  function cancel(): void {
    if (!activeRequest) return
    clearTimer(reconnectTimer)
    reconnectTimer = null
    if (socket?.readyState === SOCKET_OPEN) {
      socket.send(JSON.stringify({
        type: 'chat.cancel',
        request_id: activeRequest.request_id,
        conversation_id: activeRequest.conversation_id,
      }))
    }
    flushPendingDelta()
    stopHeartbeatTimeout()
    activeRequest = null
    state.value = 'cancelled'
    errorMessage.value = '已停止生成，已收到的内容会保留在当前会话中。'
  }

  async function retry(): Promise<void> {
    if (!activeRequest) return
    errorMessage.value = ''
    reconnectAttempt.value = 0
    try {
      await connect()
      transmitActiveRequest()
    } catch (error: unknown) {
      state.value = 'error'
      errorMessage.value = error instanceof Error ? error.message : '重新连接失败。'
    }
  }

  function disconnect(): void {
    intentionalClose = true
    clearTimer(heartbeatTimer)
    clearTimer(reconnectTimer)
    clearTimer(renderTimer)
    heartbeatTimer = null
    reconnectTimer = null
    renderTimer = null
    socket?.close(1000, 'client disconnect')
    socket = null
    connectionPromise = null
    activeRequest = null
  }

  onBeforeUnmount(disconnect)

  return {
    state,
    content,
    sources,
    recommendations,
    fallback,
    errorMessage,
    reconnectAttempt,
    requestId,
    messageId,
    send,
    cancel,
    retry,
    disconnect,
  }
}

export type WebSocketChatController = ReturnType<typeof useWebSocketChat>
