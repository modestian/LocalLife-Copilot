import type { PageResult } from './api'

export type KnowledgeBaseStatus = 'ACTIVE' | 'ARCHIVED' | 'DELETED'

export interface KnowledgeBaseStatistics {
  document_count: number
  chunk_count: number
  ready_document_count: number
  failed_document_count: number
}

export interface KnowledgeBaseSummary {
  id: string
  name: string
  description: string | null
  department_id: string | null
  department_name: string | null
  owner_id: string
  owner_name: string
  embedding_model_id: string
  embedding_model_name: string
  chunk_size: number
  chunk_overlap: number
  status: KnowledgeBaseStatus
  statistics: KnowledgeBaseStatistics
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseDetail extends KnowledgeBaseSummary {
  latest_indexed_at: string | null
}

export interface KnowledgeBaseListParams {
  name?: string
  status?: KnowledgeBaseStatus
  page: number
  page_size: number
}

export interface UpdateKnowledgeBasePayload {
  name: string
  description: string | null
  owner_id: string
  embedding_model_id: string
}

export type KnowledgeBasePage = PageResult<KnowledgeBaseSummary>
