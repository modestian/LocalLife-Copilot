import { requestData } from './client'

export type FeedbackRating = -1 | 1

export interface ChatFeedbackPayload {
  conversation_id: string
  message_id: string
  rating: FeedbackRating
  correction?: string
  reason_codes: string[]
}

export async function submitChatFeedback(payload: ChatFeedbackPayload): Promise<void> {
  await requestData<unknown>({
    method: 'POST',
    url: '/api/v1/chat/feedback',
    data: payload,
    headers: { 'Idempotency-Key': crypto.randomUUID() },
  })
}
