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

function comparisonParams(payload: MerchantComparisonRequest): URLSearchParams {
  const params = new URLSearchParams()
  for (const merchantId of payload.merchant_ids) params.append('merchant_ids', merchantId)
  if (payload.start_date) params.set('start_date', payload.start_date)
  if (payload.end_date) params.set('end_date', payload.end_date)
  return params
}

export const merchantInsightsApi = {
  compare(payload: MerchantComparisonRequest): Promise<MerchantComparisonResult> {
    return requestData({
      method: 'GET',
      url: '/api/v1/analytics/compare',
      // FastAPI expects repeated `merchant_ids` query parameters, not the
      // bracket notation Axios uses for arrays in plain objects.
      params: comparisonParams(payload),
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
