import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useWebSocketChat } from './useWebSocketChat'

class FakeSocket {
  static instances: FakeSocket[] = []
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  sent: string[] = []

  constructor(readonly url: string) {
    FakeSocket.instances.push(this)
  }

  open(): void {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }

  message(payload: object): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.readyState = 3
    this.onclose?.(new CloseEvent('close'))
  }
}

function setupChat(options: Parameters<typeof useWebSocketChat>[0] = {}) {
  let chat!: ReturnType<typeof useWebSocketChat>
  const wrapper = mount(defineComponent({
    setup() {
      chat = useWebSocketChat({
        getToken: vi.fn().mockResolvedValue('short-lived-token'),
        buildUrl: (token) => `wss://example.test/ws?access_token=${token}`,
        createSocket: (url) => new FakeSocket(url),
        heartbeatTimeoutMs: 1_000,
        reconnectBaseDelayMs: 100,
        renderBufferMs: 20,
        ...options,
      })
      return () => h('div')
    },
  }))
  return { chat, wrapper }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useWebSocketChat', () => {
  it('keeps Markdown deltas ordered and replies to heartbeat pings', async () => {
    const { chat, wrapper } = setupChat()
    const sending = chat.send('conversation-1', '推荐咖啡馆')
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1))
    const socket = FakeSocket.instances[0]
    socket.open()
    await sending

    socket.message({ type: 'chat.delta', delta: '第一段' })
    socket.message({ type: 'chat.delta', delta: '，第二段' })
    await vi.advanceTimersByTimeAsync(20)
    socket.message({ type: 'ping' })
    socket.message({ type: 'chat.completed', message_id: 'message-1' })

    expect(chat.content.value).toBe('第一段，第二段')
    expect(socket.sent.map((value) => JSON.parse(value))).toContainEqual({ type: 'pong' })
    expect(chat.state.value).toBe('completed')
    wrapper.unmount()
  })

  it('sends a cancellation event and preserves received content', async () => {
    const { chat, wrapper } = setupChat()
    const sending = chat.send('conversation-1', '继续推荐')
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1))
    const socket = FakeSocket.instances[0]
    socket.open()
    await sending
    const request = JSON.parse(socket.sent[0]) as { request_id: string }
    socket.message({ type: 'chat.delta', delta: '已收到的回答' })

    chat.cancel()

    expect(chat.content.value).toBe('已收到的回答')
    expect(socket.sent.map((value) => JSON.parse(value))).toContainEqual(expect.objectContaining({
      type: 'chat.cancel',
      request_id: request.request_id,
    }))
    expect(chat.state.value).toBe('cancelled')
    wrapper.unmount()
  })

  it('reconnects after heartbeat timeout with the same request id', async () => {
    const getToken = vi.fn()
      .mockResolvedValueOnce('token-1')
      .mockResolvedValueOnce('token-2')
    const { chat, wrapper } = setupChat({ getToken })
    const sending = chat.send('conversation-1', '恢复回答')
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1))
    const firstSocket = FakeSocket.instances[0]
    firstSocket.open()
    await sending
    const firstRequest = JSON.parse(firstSocket.sent[0]) as { request_id: string }

    await vi.advanceTimersByTimeAsync(1_000)
    expect(chat.state.value).toBe('reconnecting')
    expect(chat.errorMessage.value).toContain('心跳超时')
    await vi.advanceTimersByTimeAsync(100)
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(2))
    const secondSocket = FakeSocket.instances[1]
    secondSocket.open()
    await vi.waitFor(() => expect(secondSocket.sent).toHaveLength(1))
    const secondRequest = JSON.parse(secondSocket.sent[0]) as { request_id: string }

    expect(secondRequest.request_id).toBe(firstRequest.request_id)
    expect(getToken).toHaveBeenCalledTimes(2)
    expect(chat.state.value).toBe('streaming')
    wrapper.unmount()
  })

  it('exposes server errors for an actionable retry state', async () => {
    const { chat, wrapper } = setupChat()
    const sending = chat.send('conversation-1', '触发错误')
    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1))
    const socket = FakeSocket.instances[0]
    socket.open()
    await sending

    socket.message({ type: 'chat.error', code: 'MODEL_UNAVAILABLE', message: '模型服务暂不可用' })

    expect(chat.state.value).toBe('error')
    expect(chat.errorMessage.value).toBe('模型服务暂不可用')
    wrapper.unmount()
  })
})
