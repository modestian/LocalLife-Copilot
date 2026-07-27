import type {
  CloneKnowledgeBasePayload,
  CreateKnowledgeBasePayload,
  KnowledgeBaseDetail,
  KnowledgeBaseListParams,
  KnowledgeBasePage,
  UpdateKnowledgeBasePayload,
} from '@/types/knowledge-base'
import type { AcceptedTask } from '@/types/task'

import { requestData } from './client'

type KnowledgeBaseWireItem = Partial<KnowledgeBaseDetail> & {
  id: string
  name: string
  owner_id: string
  status: KnowledgeBaseDetail['status']
  embedding_model_version_id?: string
}

type KnowledgeBaseWirePage = Omit<KnowledgeBasePage, 'items' | 'total'> & {
  items: KnowledgeBaseWireItem[]
  total?: number
}

const emptyStatistics = {
  document_count: 0,
  chunk_count: 0,
  ready_document_count: 0,
  failed_document_count: 0,
}

function normalizeKnowledgeBase(item: KnowledgeBaseWireItem): KnowledgeBaseDetail {
  return {
    id: item.id,
    name: item.name,
    description: item.description ?? null,
    department_id: item.department_id ?? null,
    department_name: item.department_name ?? null,
    owner_id: item.owner_id,
    owner_name: item.owner_name?.trim() || '',
    embedding_model_id:
      item.embedding_model_id || item.embedding_model_version_id || '',
    embedding_model_name: item.embedding_model_name?.trim() || '',
    chunk_size: item.chunk_size ?? 0,
    chunk_overlap: item.chunk_overlap ?? 0,
    status: item.status,
    statistics: {
      ...emptyStatistics,
      ...item.statistics,
    },
    created_at: item.created_at ?? '',
    updated_at: item.updated_at ?? '',
    latest_indexed_at: item.latest_indexed_at ?? null,
  }
}

export const knowledgeBaseApi = {
  create(payload: CreateKnowledgeBasePayload): Promise<KnowledgeBaseDetail> {
    return requestData({
      method: 'POST',
      url: '/api/v1/knowledge-bases',
      data: payload,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },

  async list(params: KnowledgeBaseListParams): Promise<KnowledgeBasePage> {
    const result = await requestData<KnowledgeBaseWirePage>({
      method: 'GET',
      url: '/api/v1/knowledge-bases',
      params,
    })
    return {
      ...result,
      items: result.items.map(normalizeKnowledgeBase),
      total: result.total ?? result.items.length,
    }
  },

  async get(id: string): Promise<KnowledgeBaseDetail> {
    const result = await requestData<KnowledgeBaseWireItem>({
      method: 'GET',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}`,
    })
    return normalizeKnowledgeBase(result)
  },

  async update(
    id: string,
    payload: UpdateKnowledgeBasePayload,
  ): Promise<KnowledgeBaseDetail> {
    const result = await requestData<KnowledgeBaseWireItem>({
      method: 'PATCH',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}`,
      data: payload,
    })
    return normalizeKnowledgeBase(result)
  },

  delete(id: string, purge = false): Promise<AcceptedTask> {
    return requestData({
      method: 'DELETE',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}`,
      params: purge ? { purge: true } : undefined,
    })
  },

  clone(id: string, payload: CloneKnowledgeBasePayload): Promise<AcceptedTask> {
    return requestData({
      method: 'POST',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}/clone`,
      data: payload,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },

  reindex(id: string): Promise<AcceptedTask> {
    return requestData({
      method: 'POST',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}/reindex`,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },
}
