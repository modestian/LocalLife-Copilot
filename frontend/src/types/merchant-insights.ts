import type { AnalyticsDateRange, Sentiment } from './merchant-analytics'

export interface MerchantComparisonRequest extends AnalyticsDateRange {
  /** 后端按统一时间窗比较 2～4 家商家。 */
  merchant_ids: string[]
}

export interface ComparisonMerchantMetric {
  merchant_id: string
  merchant_name: string
  sample_count: number
  positive_rate: number
  aspect_counts: Record<string, number>
  negative_reason_counts: Record<string, number>
}

export interface MerchantComparisonResult {
  period_start: string
  period_end: string
  metric_definition: string
  minimum_sample_size: number
  insufficient_data: boolean
  merchants: ComparisonMerchantMetric[]
}

export type ReplyTone = 'EMPATHETIC' | 'PROFESSIONAL' | 'CONCISE'

export interface ReplySuggestionRequest {
  tone: ReplyTone
  aspect_labels: string[]
  prohibited_commitments: string[]
}

export interface EvidenceReview {
  review_id: string
  review_text: string
  sentiment: Sentiment | null
  reviewed_at: string | null
}

export interface ReplySuggestionResult {
  draft: string
  model_version: string
  prompt_version: string
  generated_at: string
  evidence_review_ids: string[]
}

export interface BusinessSuggestionRequest extends AnalyticsDateRange {
  focus_aspects?: string[]
}

export interface BusinessSuggestion {
  id: string
  title: string
  content: string
  confidence: number
  period_start: string
  period_end: string
  evidence_review_ids: string[]
  evidence_reviews: EvidenceReview[]
}

export interface BusinessSuggestionResult {
  suggestions: BusinessSuggestion[]
  insufficient_data: boolean
  evidence_conflict: boolean
  model_version: string
  prompt_version: string
  generated_at: string
}

export interface ReplySubmitRequest {
  content: string
  tone: ReplyTone
  source: 'SUGGESTION' | 'MANUAL'
}

export interface MerchantReply {
  id: string
  review_id: string
  merchant_id: string
  content: string
  tone: ReplyTone
  source: 'SUGGESTION' | 'MANUAL'
  status: 'PENDING' | 'PUBLISHED' | 'REJECTED'
  created_at: string
  updated_at: string
}
