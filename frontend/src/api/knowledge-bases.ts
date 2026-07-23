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

export const knowledgeBaseApi = {
  create(payload: CreateKnowledgeBasePayload): Promise<KnowledgeBaseDetail> {
    return requestData({
      method: 'POST',
      url: '/api/v1/knowledge-bases',
      data: payload,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
  },

  list(params: KnowledgeBaseListParams): Promise<KnowledgeBasePage> {
    return requestData({
      method: 'GET',
      url: '/api/v1/knowledge-bases',
      params,
    })
  },

  get(id: string): Promise<KnowledgeBaseDetail> {
    return requestData({
      method: 'GET',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}`,
    })
  },

  update(id: string, payload: UpdateKnowledgeBasePayload): Promise<KnowledgeBaseDetail> {
    return requestData({
      method: 'PATCH',
      url: `/api/v1/knowledge-bases/${encodeURIComponent(id)}`,
      data: payload,
    })
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
