import type { SearchRequest, SearchResponse } from '@/types/search'

import { requestData } from './client'

export const searchApi = {
  search(payload: SearchRequest): Promise<SearchResponse> {
    return requestData({
      method: 'POST',
      url: '/api/v1/search',
      data: payload,
    })
  },
}
