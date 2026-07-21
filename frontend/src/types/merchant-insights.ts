import type { AnalyticsDateRange, Sentiment } from './merchant-analytics'

export interface MerchantComparisonRequest extends AnalyticsDateRange {
  /** 后端按统一时间窗比较 2～4 家商家。 */
  merchant_ids: string[]
}

export interface ComparisonSummary {
  merchant_id: string
  positive: number
  neutral: number
  negative: number
  total: number
  positive_rate: number
  negative_rate: number
}

export interface AspectComparisonMetric {
  merchant_id: string
  positive: number
  neutral: number
  negative: number
  total: number
  positive_rate: number
}

export interface AspectComparisonRow {
  aspect: string
  merchants: AspectComparisonMetric[]
}

export interface NegativeReasonComparisonMetric {
  merchant_id: string
  count: number
}

export interface NegativeReasonComparisonRow {
  reason: string
  merchants: NegativeReasonComparisonMetric[]
}

export interface MerchantComparisonResult {
  merchants: string[]
  summary: ComparisonSummary[]
  aspect_comparison: AspectComparisonRow[]
  negative_reason_comparison: NegativeReasonComparisonRow[]
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
