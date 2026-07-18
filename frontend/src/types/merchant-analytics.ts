export type Sentiment = 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE'

export type TrendGranularity = 'day' | 'week' | 'month'

export interface SentimentTrendPoint {
  period: string
  positive: number
  neutral: number
  negative: number
}

export interface NegativeReasonPoint {
  reason: string
  count: number
}

export interface AnalyticsReview {
  id: string
  review_text: string
  sentiment: Sentiment
  confidence: number
  aspect_labels: string[]
  negative_reasons: string[]
  review_date: string | null
}

export interface AnalyticsDateRange {
  start_date?: string
  end_date?: string
}

export interface SentimentTrendQuery extends AnalyticsDateRange {
  granularity: TrendGranularity
}

export interface ReviewDrillDownQuery extends AnalyticsDateRange {
  sentiment?: Sentiment
  negative_reason?: string
  limit?: number
  offset?: number
}
