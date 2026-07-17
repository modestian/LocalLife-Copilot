import { requestData } from './client'

export interface SearchFilters {
  category?: string[]
  price_cent_lte?: number
  distance_meter_lte?: number
  open_now?: boolean
  document_type?: string[]
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
}

export interface SearchResult {
  chunk_id: string
  document_id: string
  merchant_id?: string | null
  content: string
  source_location: string
  source_url: string
  score: number
  score_detail: SearchScoreDetail
}

export async function debugSearch(request: SearchRequest): Promise<SearchResult[]> {
  const response = await requestData<{ items?: SearchResult[] } | SearchResult[]>({
    method: 'POST',
    url: '/api/v1/search',
    data: request,
  })

  return Array.isArray(response) ? response : response.items ?? []
}
