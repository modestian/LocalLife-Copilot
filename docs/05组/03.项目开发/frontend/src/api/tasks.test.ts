import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { taskApi } from './tasks'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('task API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset().mockResolvedValue({}))

  it('loads the documented task status resource', async () => {
    await taskApi.get('task/id')

    expect(requestData).toHaveBeenCalledWith({
      method: 'GET',
      url: '/api/v1/tasks/task%2Fid',
    })
  })

  it('posts cancel and retry commands to the same task', async () => {
    await taskApi.cancel('task/id')
    await taskApi.retry('task/id')

    expect(requestData).toHaveBeenNthCalledWith(1, {
      method: 'POST',
      url: '/api/v1/tasks/task%2Fid/cancel',
    })
    expect(requestData).toHaveBeenNthCalledWith(2, {
      method: 'POST',
      url: '/api/v1/tasks/task%2Fid/retry',
    })
  })
})
