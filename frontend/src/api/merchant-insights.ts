import type {
  BusinessSuggestionRequest,
  BusinessSuggestionResult,
  MerchantComparisonRequest,
  MerchantComparisonResult,
  ReplySuggestionRequest,
  ReplySuggestionResult,
} from '@/types/merchant-insights'

import { requestData } from './client'

function merchantUrl(merchantId: string, resource: string): string {
  return `/api/v1/merchants/${encodeURIComponent(merchantId)}/${resource}`
}

export const merchantInsightsApi = {
  compare(payload: MerchantComparisonRequest): Promise<MerchantComparisonResult> {
    return requestData({
      method: 'POST',
      url: '/api/v1/merchants/compare',
      data: payload,
    })
  },

  getReplySuggestion(
    reviewId: string,
    payload: ReplySuggestionRequest,
  ): Promise<ReplySuggestionResult> {
    return requestData({
      method: 'POST',
      url: `/api/v1/reviews/${encodeURIComponent(reviewId)}/reply-suggestions`,
      data: payload,
    })
  },

  getBusinessSuggestions(
    merchantId: string,
    payload: BusinessSuggestionRequest,
  ): Promise<BusinessSuggestionResult> {
    return requestData({
      method: 'POST',
      url: merchantUrl(merchantId, 'business-suggestions'),
      data: payload,
    })
  },
}
