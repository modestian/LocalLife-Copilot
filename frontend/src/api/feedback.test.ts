import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { feedbackApi } from './feedback'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('feedback API', () => {
  const requestId = '00000000-0000-4000-8000-000000000001'

  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue(undefined)
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId)
  })

  it('posts the documented feedback payload with an idempotency key', async () => {
    await feedbackApi.submit({
      conversation_id: 'conversation-1',
      message_id: 'message-1',
      rating: -1,
      correction: '该店周一闭店。',
      reason_codes: ['FACT_ERROR', 'OUTDATED'],
    })

    expect(requestData).toHaveBeenCalledWith({
      method: 'POST',
      url: '/api/v1/chat/feedback',
      data: {
        conversation_id: 'conversation-1',
        message_id: 'message-1',
        rating: -1,
        correction: '该店周一闭店。',
        reason_codes: ['FACT_ERROR', 'OUTDATED'],
      },
      headers: { 'Idempotency-Key': requestId },
    })
  })
})
