export type FeedbackRating = -1 | 1

export interface ChatFeedbackPayload {
  conversation_id: string
  message_id: string
  rating: FeedbackRating
  correction?: string
  reason_codes?: string[]
}

export interface FeedbackQueryParams {
  rating?: FeedbackRating
  task_type?: string
  review_status?: string
  start_date?: string
  end_date?: string
}

export interface FeedbackEntry {
  id: string
  user_id: string
  message_id: string
  conversation_id: string | null
  rating: FeedbackRating
  correction: string | null
  reason_codes: string[]
  version: number
  review_status: string
  created_at: string
  updated_at: string
}

export interface FeedbackApi {
  submit: (payload: ChatFeedbackPayload) => Promise<void>
  query: (params?: FeedbackQueryParams) => Promise<FeedbackEntry[]>
}
