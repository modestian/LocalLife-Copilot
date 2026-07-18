import type {
  AnalyticsDateRange,
  AnalyticsReview,
  NegativeReasonPoint,
  ReviewDrillDownQuery,
  SentimentTrendPoint,
  SentimentTrendQuery,
} from '@/types/merchant-analytics'

import { requestData } from './client'

function analyticsUrl(merchantId: string, resource: string): string {
  return `/api/v1/merchants/${encodeURIComponent(merchantId)}/analytics/${resource}`
}

export const merchantAnalyticsApi = {
  getSentimentTrend(
    merchantId: string,
    query: SentimentTrendQuery,
  ): Promise<SentimentTrendPoint[]> {
    return requestData({
      method: 'GET',
      url: analyticsUrl(merchantId, 'sentiment-trend'),
      params: query,
    })
  },

  getNegativeReasons(
    merchantId: string,
    query: AnalyticsDateRange = {},
  ): Promise<NegativeReasonPoint[]> {
    return requestData({
      method: 'GET',
      url: analyticsUrl(merchantId, 'negative-reasons'),
      params: query,
    })
  },

  getReviews(
    merchantId: string,
    query: ReviewDrillDownQuery = {},
  ): Promise<AnalyticsReview[]> {
    return requestData({
      method: 'GET',
      url: analyticsUrl(merchantId, 'reviews'),
      params: query,
    })
  },
}
