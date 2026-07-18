import type { FeedbackApi } from '@/types/feedback'

import { requestData } from './client'

export const feedbackApi: FeedbackApi = {
  submit(payload) {
    return requestData<void>({
      method: 'POST',
      url: '/api/v1/chat/feedback',
      data: payload,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },
}
