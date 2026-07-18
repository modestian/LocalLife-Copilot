export type FeedbackRating = -1 | 1

export interface ChatFeedbackPayload {
  conversation_id: string
  message_id: string
  rating: FeedbackRating
  correction?: string
  reason_codes?: string[]
}

export interface FeedbackApi {
  submit: (payload: ChatFeedbackPayload) => Promise<void>
}
