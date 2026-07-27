export type SearchDocumentType = 'review' | 'merchant'

export interface SearchFilters {
  category?: string[]
  price_cent_lte?: number
  distance_meter_lte?: number
  open_now?: boolean
  document_type?: SearchDocumentType[]
}

export interface SearchRequest {
  query: string
  knowledge_base_ids: string[]
  top_k: number
  vector_weight: number
  keyword_weight: number
  rerank: boolean
  filters: SearchFilters
}

export interface SearchScoreDetail {
  bm25: number
  vector: number
  fusion: number
  rerank?: number | null
}

export interface SearchMatchExplanation {
  recall_sources: Array<'bm25' | 'vector'>
  keyword_matched: boolean
  semantic_matched: boolean
  reranked: boolean
}

export interface SearchHit {
  chunk_id: string
  document_id: string
  merchant_id?: string | null
  content: string
  source_location: string
  source_url: string
  score: number
  score_detail: SearchScoreDetail
  match_explanation: SearchMatchExplanation
}

export interface SearchResponse {
  items: SearchHit[]
  total?: number
  took_ms?: number
  fallback: boolean
  fallback_reason?: string | null
  applied_filters: SearchFilters
}
