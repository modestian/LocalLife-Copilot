import type {
  BusinessSuggestionRequest,
  BusinessSuggestionResult,
  MerchantComparisonRequest,
  MerchantComparisonResult,
  MerchantReply,
  ReplySuggestionRequest,
  ReplySuggestionResult,
  ReplySubmitRequest,
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

  submitReply(
    reviewId: string,
    payload: ReplySubmitRequest,
  ): Promise<MerchantReply> {
    return requestData({
      method: 'POST',
      url: `/api/v1/reviews/${encodeURIComponent(reviewId)}/replies`,
      data: payload,
    })
  },

  getReplies(reviewId: string): Promise<{ items: MerchantReply[]; total: number }> {
    return requestData({
      method: 'GET',
      url: `/api/v1/reviews/${encodeURIComponent(reviewId)}/replies`,
    })
  },
}
