import type { AnalyticsDateRange, Sentiment } from './merchant-analytics'

export interface MerchantComparisonRequest extends AnalyticsDateRange {
  /** 当前商家加 2～4 家公开竞品；后端正式契约待 ST-402 冻结。 */
  merchant_ids: string[]
}

export interface ComparisonMerchantMetric {
  merchant_id: string
  merchant_name: string
  sample_count: number
  positive_rate: number
  avg_rating: number | null
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
