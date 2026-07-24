import { requestData } from './client'

export interface ReviewItem {
  id: string
  merchant_id: string
  content: string
  rating: number | null
  status: string
  created_at: string
}

export interface ReviewListResponse {
  items: ReviewItem[]
  page: number
  page_size: number
  total: number
}

export interface SubmitReviewPayload {
  content: string
  rating: number
}

export interface SubmitReviewResponse {
  id: string
  merchant_id: string
  status: string
  rating: number | null
  created_at: string
}

export interface MerchantDirectoryItem {
  id: string
  name: string
  category: string
  address: string
}

export interface AdminReviewItem {
  id: string
  merchant_id: string
  author: string | null
  content: string
  rating: number | null
  status: string
  source_type: string
  created_at: string | null
}

export interface AdminReviewListResponse {
  items: AdminReviewItem[]
  page: number
  page_size: number
  total: number
}

export interface ModeratePayload {
  decision: 'APPROVE' | 'REJECT'
  reason: string
}

export const reviewsApi = {
  submitReview(merchantId: string, payload: SubmitReviewPayload): Promise<SubmitReviewResponse> {
    return requestData({
      method: 'POST',
      url: `/api/v1/merchants/${encodeURIComponent(merchantId)}/reviews`,
      data: payload,
    })
  },

  getMyReviews(page = 1, pageSize = 20): Promise<ReviewListResponse> {
    return requestData({
      method: 'GET',
      url: '/api/v1/users/me/reviews',
      params: { page, page_size: pageSize },
    })
  },

  getMerchantDirectory(keyword?: string, limit = 50): Promise<{ items: MerchantDirectoryItem[] }> {
    return requestData({
      method: 'GET',
      url: '/api/v1/merchants/directory',
      params: { keyword, limit },
    })
  },

  getPendingReviews(
    status = 'PENDING',
    page = 1,
    pageSize = 20,
  ): Promise<AdminReviewListResponse> {
    return requestData({
      method: 'GET',
      url: '/api/v1/reviews/pending',
      params: { status, page, page_size: pageSize },
    })
  },

  moderateReview(reviewId: string, payload: ModeratePayload): Promise<{ id: string; status: string }> {
    return requestData({
      method: 'POST',
      url: `/api/v1/reviews/${encodeURIComponent(reviewId)}/moderate`,
      data: payload,
    })
  },
}
