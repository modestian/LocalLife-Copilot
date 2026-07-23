import type { PageResult } from './api'
import type { AcceptedTask } from './task'

export type JsonObject = Record<string, unknown>

export interface DataSourceCreatePayload {
  name: string
  source_type: 'CSV' | 'FILE' | 'WEB' | 'API'
  source_uri: string
  source_sha256: string
  source_size_bytes: number
  mime_type?: string
  parser_name?: string | null
  parser_version?: string
  cleaning_config?: JsonObject
  splitter_config?: JsonObject
}

export interface DataSource {
  id: string
  knowledge_base_id: string
  name: string
  source_type: string
  status: string
  [key: string]: unknown
}

export interface MerchantListParams {
  category?: string
  price_cent_lte?: number
  open_now?: boolean
  latitude?: number
  longitude?: number
  distance_meter_lte?: number
  page?: number
  page_size?: number
}

export interface Merchant {
  id: string
  name: string
  [key: string]: unknown
}

export interface MerchantReviewListParams {
  sentiment?: string
  tag?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

export interface MerchantReview {
  id: string
  merchant_id: string
  content?: string
  [key: string]: unknown
}

export interface AnalysisJobPayload {
  mode: 'FULL' | 'INCREMENTAL'
}

export interface ModerationCaseListParams {
  status?: string
  page?: number
  page_size?: number
}

export interface ModerationCase {
  id: string
  status: string
  [key: string]: unknown
}

export interface ModerationDecisionPayload {
  decision: 'APPROVE' | 'REJECT' | 'ESCALATE'
  reason: string
}

export interface SensitiveWordPayload {
  word: string
  scope?: 'INPUT' | 'OUTPUT' | 'BOTH'
  match_type?: 'CONTAINS' | 'EXACT' | 'REGEX'
  severity?: 'LOW' | 'MEDIUM' | 'HIGH'
}

export interface PromptCreatePayload {
  code: string
  name: string
  scene: string
  description?: string | null
  content: string
  variables?: JsonObject
}

export interface ModelCreatePayload {
  code: string
  name: string
  version: string
  task_type: string
  provider: string
  base_model_ref: string
  adapter_uri: string
  artifact_sha256: string
  dimension?: number | null
  labels?: string[] | null
  metrics?: JsonObject | null
}

export type MerchantPage = PageResult<Merchant>
export type MerchantReviewPage = PageResult<MerchantReview>
export type ModerationCasePage = PageResult<ModerationCase>
export type OperationTask = AcceptedTask
