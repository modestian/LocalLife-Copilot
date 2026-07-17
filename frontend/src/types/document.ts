import type { PageResult } from './api'
import type { AcceptedTask } from './task'

export type DocumentStatus =
  | 'UPLOADED'
  | 'PARSING'
  | 'INDEXING'
  | 'READY'
  | 'FAILED'
  | 'ARCHIVED'
  | 'DELETED'

export type SplitterStrategy = 'recursive' | 'semantic'

export interface DocumentSummary {
  id: string
  knowledge_base_id: string
  display_name: string
  source_type: string
  mime_type: string | null
  status: DocumentStatus
  current_version_no: number
  file_size: number | null
  chunk_count: number
  last_error_code: string | null
  created_at: string
  updated_at: string
}

export interface DocumentVersionSummary {
  id: string
  version_no: number
  file_sha256: string
  file_size: number
  parser_name: string
  parser_version: string
  is_current: boolean
  created_at: string
}

export interface DocumentDetail extends DocumentSummary {
  source_key: string
  metadata: Record<string, unknown>
  versions: DocumentVersionSummary[]
}

export interface DocumentChunkPreview {
  id: string
  chunk_no: number
  content: string
  token_count: number
  page_number: number | null
  metadata: Record<string, unknown>
}

export interface DocumentPreview {
  document_id: string
  version_no: number
  original_content: string
  original_truncated: boolean
  chunks: DocumentChunkPreview[]
  chunk_page: number
  chunk_page_size: number
  chunk_total: number
}

export interface DocumentListParams {
  page: number
  page_size: number
  status?: Exclude<DocumentStatus, 'DELETED'>
}

export interface DocumentPreviewParams {
  version_no?: number
  keyword?: string
  chunk_page?: number
  chunk_page_size?: number
}

export interface UploadDocumentsPayload {
  files: File[]
  splitter: SplitterStrategy
  chunk_size: number
  chunk_overlap: number
  cleaning_profile_id?: string
  force_new_version: boolean
}

export type DocumentPage = PageResult<DocumentSummary>

export type { AcceptedTask }
