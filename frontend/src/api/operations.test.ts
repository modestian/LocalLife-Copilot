import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import {
  dataSourceApi,
  governanceApi,
  merchantApi,
  moderationApi,
  observabilityApi,
} from './operations'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('documented operational API clients', () => {
  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue({})
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000003')
  })

  it('uses the documented data-source and merchant routes', async () => {
    await dataSourceApi.ingest('source/id')
    await merchantApi.list()
    await merchantApi.get('merchant/id')
    await merchantApi.listReviews('merchant/id')
    await merchantApi.createAnalysisJob('merchant/id', { mode: 'FULL' })
    await merchantApi.getSentiment('merchant/id')
    await merchantApi.getTopics('merchant/id')

    expect(requestData).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        method: 'POST',
        url: '/api/v1/data-sources/source%2Fid/ingest',
      }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ method: 'GET', url: '/api/v1/merchants' }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({ method: 'GET', url: '/api/v1/merchants/merchant%2Fid' }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      4,
      expect.objectContaining({
        method: 'GET',
        url: '/api/v1/merchants/merchant%2Fid/reviews',
      }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      5,
      expect.objectContaining({
        method: 'POST',
        url: '/api/v1/merchants/merchant%2Fid/analysis-jobs',
      }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      6,
      expect.objectContaining({
        method: 'GET',
        url: '/api/v1/merchants/merchant%2Fid/sentiment',
      }),
    )
    expect(requestData).toHaveBeenNthCalledWith(
      7,
      expect.objectContaining({
        method: 'GET',
        url: '/api/v1/merchants/merchant%2Fid/topics',
      }),
    )
  })

  it('covers moderation, governance, audit, chat-log, and overview routes', async () => {
    await moderationApi.listCases()
    await moderationApi.decide('case/id', { decision: 'APPROVE', reason: 'checked' })
    await moderationApi.listSensitiveWords()
    await moderationApi.createSensitiveWord({ word: '测试词' })
    await governanceApi.createPrompt({
      code: 'assistant',
      name: 'assistant',
      scene: 'chat',
      content: 'prompt',
    })
    await governanceApi.publishPrompt('prompt/id', 'approved')
    await governanceApi.rollbackPrompt('prompt/id', 'regression')
    await governanceApi.createModel({
      code: 'sentiment',
      name: 'sentiment',
      version: 'v2',
      task_type: 'sentiment_classification',
      provider: 'local-lora',
      base_model_ref: 'base',
      adapter_uri: '/models/sentiment-v2',
      artifact_sha256: 'a'.repeat(64),
    })
    await governanceApi.rollbackModel('model/id', {
      scene: 'sentiment',
      environment: 'production',
      reason: 'regression',
    })
    await observabilityApi.getAuditLogs()
    await observabilityApi.getChatLogs()
    await observabilityApi.getOverview()

    const calls = vi.mocked(requestData).mock.calls.map(([request]) => [
      request.method,
      request.url,
    ])
    expect(calls).toEqual([
      ['GET', '/api/v1/moderation/cases'],
      ['POST', '/api/v1/moderation/cases/case%2Fid/decision'],
      ['GET', '/api/v1/sensitive-words'],
      ['POST', '/api/v1/sensitive-words'],
      ['POST', '/api/v1/prompts'],
      ['POST', '/api/v1/prompts/prompt%2Fid/publish'],
      ['POST', '/api/v1/prompts/prompt%2Fid/rollback'],
      ['POST', '/api/v1/models'],
      ['POST', '/api/v1/models/model%2Fid/rollback'],
      ['GET', '/api/v1/audit-logs'],
      ['GET', '/api/v1/chat-logs'],
      ['GET', '/api/v1/analytics/overview'],
    ])
  })
})
