import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { merchantDirectoryApi } from './merchants'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('merchant directory API', () => {
  beforeEach(() => {
    vi.mocked(requestData).mockReset()
  })

  it('loads the merchant name used by the scoped merchant switcher', async () => {
    await merchantDirectoryApi.getMerchant('merchant/id')

    expect(requestData).toHaveBeenCalledWith({
      method: 'GET',
      url: '/api/v1/merchants/merchant%2Fid',
    })
  })
})
