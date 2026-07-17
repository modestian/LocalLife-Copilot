import type {
  KnowledgeBaseDetail,
  KnowledgeBaseListParams,
  KnowledgeBasePage,
  UpdateKnowledgeBasePayload,
} from '@/types/knowledge-base'

import { requestData } from './client'

export const knowledgeBaseApi = {
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
}
