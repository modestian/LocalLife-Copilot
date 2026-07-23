import type {
  AnalysisJobPayload,
  DataSource,
  DataSourceCreatePayload,
  JsonObject,
  Merchant,
  MerchantListParams,
  MerchantPage,
  MerchantReviewListParams,
  MerchantReviewPage,
  ModerationCaseListParams,
  ModerationCasePage,
  ModerationDecisionPayload,
  ModelCreatePayload,
  OperationTask,
  PromptCreatePayload,
  SensitiveWordPayload,
} from '@/types/operations'

import { requestData } from './client'

const encoded = (value: string): string => encodeURIComponent(value)
const idempotencyHeaders = (): Record<string, string> => ({
  'Idempotency-Key': crypto.randomUUID(),
})

export const dataSourceApi = {
  create(knowledgeBaseId: string, payload: DataSourceCreatePayload): Promise<DataSource> {
    return requestData({
      method: 'POST',
      url: `/api/v1/knowledge-bases/${encoded(knowledgeBaseId)}/data-sources`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  ingest(dataSourceId: string): Promise<OperationTask> {
    return requestData({
      method: 'POST',
      url: `/api/v1/data-sources/${encoded(dataSourceId)}/ingest`,
      headers: idempotencyHeaders(),
    })
  },
}

export const merchantApi = {
  list(params: MerchantListParams = {}): Promise<MerchantPage> {
    return requestData({ method: 'GET', url: '/api/v1/merchants', params })
  },

  get(merchantId: string): Promise<Merchant> {
    return requestData({ method: 'GET', url: `/api/v1/merchants/${encoded(merchantId)}` })
  },

  listReviews(
    merchantId: string,
    params: MerchantReviewListParams = {},
  ): Promise<MerchantReviewPage> {
    return requestData({
      method: 'GET',
      url: `/api/v1/merchants/${encoded(merchantId)}/reviews`,
      params,
    })
  },

  createAnalysisJob(merchantId: string, payload: AnalysisJobPayload): Promise<OperationTask> {
    return requestData({
      method: 'POST',
      url: `/api/v1/merchants/${encoded(merchantId)}/analysis-jobs`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  getSentiment(merchantId: string, params: JsonObject = {}): Promise<JsonObject> {
    return requestData({
      method: 'GET',
      url: `/api/v1/merchants/${encoded(merchantId)}/sentiment`,
      params,
    })
  },

  getTopics(merchantId: string, params: JsonObject = {}): Promise<JsonObject> {
    return requestData({
      method: 'GET',
      url: `/api/v1/merchants/${encoded(merchantId)}/topics`,
      params,
    })
  },
}

export const moderationApi = {
  listCases(params: ModerationCaseListParams = {}): Promise<ModerationCasePage> {
    return requestData({ method: 'GET', url: '/api/v1/moderation/cases', params })
  },

  decide(caseId: string, payload: ModerationDecisionPayload): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: `/api/v1/moderation/cases/${encoded(caseId)}/decision`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  listSensitiveWords(params: JsonObject = {}): Promise<JsonObject> {
    return requestData({ method: 'GET', url: '/api/v1/sensitive-words', params })
  },

  createSensitiveWord(payload: SensitiveWordPayload): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: '/api/v1/sensitive-words',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },
}

export const governanceApi = {
  createPrompt(payload: PromptCreatePayload): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: '/api/v1/prompts',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  publishPrompt(promptId: string, reason: string): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: `/api/v1/prompts/${encoded(promptId)}/publish`,
      data: { reason },
      headers: idempotencyHeaders(),
    })
  },

  rollbackPrompt(promptId: string, reason: string): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: `/api/v1/prompts/${encoded(promptId)}/rollback`,
      data: { reason },
      headers: idempotencyHeaders(),
    })
  },

  createModel(payload: ModelCreatePayload): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: '/api/v1/models',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  rollbackModel(
    modelId: string,
    payload: { scene: string; environment: string; reason: string },
  ): Promise<JsonObject> {
    return requestData({
      method: 'POST',
      url: `/api/v1/models/${encoded(modelId)}/rollback`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },
}

export const observabilityApi = {
  getAuditLogs(params: JsonObject = {}): Promise<JsonObject> {
    return requestData({ method: 'GET', url: '/api/v1/audit-logs', params })
  },

  getChatLogs(params: JsonObject = {}): Promise<JsonObject> {
    return requestData({ method: 'GET', url: '/api/v1/chat-logs', params })
  },

  getOverview(params: JsonObject = {}): Promise<JsonObject> {
    return requestData({ method: 'GET', url: '/api/v1/analytics/overview', params })
  },
}
