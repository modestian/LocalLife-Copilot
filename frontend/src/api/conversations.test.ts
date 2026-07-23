import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { conversationApi } from './conversations'

vi.mock('./client', () => ({
  apiClient: { post: vi.fn() },
  requestData: vi.fn(),
}))

describe('conversation API', () => {
  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue({})
  })

  it('uses DELETE so the server can logically delete a conversation', async () => {
    await conversationApi.deleteConversation('conversation/id')

    expect(requestData).toHaveBeenCalledWith({
      method: 'DELETE',
      url: '/api/v1/conversations/conversation%2Fid',
    })
  })
})
