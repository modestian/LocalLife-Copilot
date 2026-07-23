import { requestData } from './client'

export interface MerchantDirectoryEntry {
  id: string
  name: string
  category: string
  address: string
}

export const merchantDirectoryApi = {
  getMerchant(merchantId: string): Promise<MerchantDirectoryEntry> {
    return requestData({
      method: 'GET',
      url: `/api/v1/merchants/${encodeURIComponent(merchantId)}`,
    })
  },
}
