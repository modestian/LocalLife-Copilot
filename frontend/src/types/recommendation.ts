export interface RecommendationSource {
  chunk_id: string
  source_location: string
  source_url: string
  content: string
  highlight_text?: string
  score: number
}

export interface MerchantRecommendation {
  merchant_id: string
  name: string
  category: string
  reason: string
  distance_meter?: number | null
  avg_price_cent?: number | null
  rating?: number | null
  business_status?: 'OPEN' | 'CLOSED' | 'UNKNOWN'
  data_updated_at: string
  source_chunk_ids: string[]
  tags?: string[]
}

export interface RecommendationFallback {
  triggered: boolean
  reason?: string
  suggestions?: string[]
}
