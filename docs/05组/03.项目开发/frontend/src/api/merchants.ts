import { requestData } from './client'

export interface MerchantDirectoryEntry {
  id: string
  name: string
  category: string
  address: string
}

export const merchantDirectoryApi = {
  listMerchants(keyword?: string): Promise<{ items: MerchantDirectoryEntry[] }> {
    return requestData({
      method: 'GET',
      url: '/api/v1/merchants/directory',
      params: keyword ? { keyword, limit: 100 } : { limit: 100 },
    })
  },
  getMerchant(merchantId: string): Promise<MerchantDirectoryEntry> {
    return requestData({
      method: 'GET',
      url: `/api/v1/merchants/${encodeURIComponent(merchantId)}`,
    })
  },
}
