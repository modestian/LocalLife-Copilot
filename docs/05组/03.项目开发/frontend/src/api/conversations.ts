import { apiClient, requestData } from './client'
import type {
  MerchantRecommendation,
  RecommendationFallback,
  RecommendationSource,
} from '@/types/recommendation'

export type ConversationScenario = 'nearby' | 'date' | 'study' | 'gathering' | 'family'
export type MessageRole = 'USER' | 'ASSISTANT'
export type MessageStatus = 'STREAMING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export interface ExploreConstraints {
  distance_km?: number
  budget_yuan?: number
  cuisine?: string
  party_size?: number
  open_now: boolean
}

export interface ChatMessage {
  id: string
  conversation_id: string
  role: MessageRole
  content: string
  status: MessageStatus
  created_at: string
  sources?: RecommendationSource[]
  recommendations?: MerchantRecommendation[]
  fallback?: RecommendationFallback
}

export interface ConversationSummary {
  id: string
  title: string
  scenario?: ConversationScenario
  status: 'ACTIVE' | 'ARCHIVED'
  updated_at: string
  message_count?: number
  preview_messages?: ChatMessage[]
}

export interface CreateConversationRequest {
  title: string
  scenario: ConversationScenario
  constraints?: ExploreConstraints
}

interface ConversationListResponse {
  items: ConversationSummary[]
}

interface MessageListResponse {
  items: ChatMessage[]
  next_cursor?: string | null
}

interface ChatCompletionResponse {
  id: string
  conversation_id: string
  message_id?: string
  choices: Array<{
    message: { role: 'assistant'; content: string }
  }>
}

export interface DeletedConversation {
  id: string
  status: 'DELETED'
}

export interface ConversationApi {
  listConversations: () => Promise<ConversationSummary[]>
  createConversation: (request: CreateConversationRequest) => Promise<ConversationSummary>
  listMessages: (conversationId: string) => Promise<ChatMessage[]>
  sendMessage: (conversationId: string, content: string) => Promise<ChatMessage>
  deleteConversation: (conversationId: string) => Promise<DeletedConversation>
  truncateConversation: (conversationId: string, messageId: string) => Promise<void>
  updateSettings: (
    conversationId: string,
    settings: Record<string, number>,
  ) => Promise<ConversationSummary>
}

export const conversationApi: ConversationApi = {
  async listConversations() {
    const data = await requestData<ConversationListResponse>({
      method: 'GET',
      url: '/api/v1/conversations',
      params: { page: 1, page_size: 50 },
    })
    return data.items
  },

  async createConversation(request) {
    return requestData<ConversationSummary>({
      method: 'POST',
      url: '/api/v1/conversations',
      data: request,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },

  async listMessages(conversationId) {
    const data = await requestData<MessageListResponse>({
      method: 'GET',
      url: `/api/v1/conversations/${conversationId}/messages`,
      params: { limit: 100 },
    })
    return data.items
  },

  async sendMessage(conversationId, content) {
    const response = await apiClient.post<ChatCompletionResponse>('/v1/chat/completions', {
      model: 'local-life-assistant',
      messages: [{ role: 'user', content }],
      conversation_id: conversationId,
      stream: false,
      temperature: 0.3,
      max_tokens: 800,
    })
    const data = response.data
    return {
      id: data.message_id ?? data.id,
      conversation_id: data.conversation_id,
      role: 'ASSISTANT',
      content: data.choices[0]?.message.content ?? '暂时没有生成有效回答，请稍后重试。',
      status: 'COMPLETED',
      created_at: new Date().toISOString(),
    }
  },

  deleteConversation(conversationId) {
    return requestData<DeletedConversation>({
      method: 'DELETE',
      url: `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
    })
  },

  truncateConversation(conversationId, messageId) {
    return requestData({
      method: 'POST',
      url: `/api/v1/conversations/${encodeURIComponent(conversationId)}/truncate`,
      data: { message_id: messageId },
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },

  updateSettings(conversationId, settings) {
    return requestData({
      method: 'PATCH',
      url: `/api/v1/conversations/${encodeURIComponent(conversationId)}/settings`,
      data: settings,
    })
  },
}
