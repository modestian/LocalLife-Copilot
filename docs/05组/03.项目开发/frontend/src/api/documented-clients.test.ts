import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { conversationApi } from './conversations'
import { documentApi } from './documents'
import { knowledgeBaseApi } from './knowledge-bases'
import { modelLifecycleApi } from './model-lifecycle'

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>()
  return { ...actual, requestData: vi.fn() }
})

describe('clients added for documented API coverage', () => {
  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue({})
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000004')
  })

  it('covers knowledge-base and document lifecycle routes', async () => {
    await knowledgeBaseApi.delete('kb/id')
    await knowledgeBaseApi.clone('kb/id', { name: 'clone' })
    await knowledgeBaseApi.reindex('kb/id')
    await documentApi.update('document/id', { display_name: 'updated.md' })
    await documentApi.reindex('document/id')

    expect(vi.mocked(requestData).mock.calls.map(([request]) => [request.method, request.url])).toEqual([
      ['DELETE', '/api/v1/knowledge-bases/kb%2Fid'],
      ['POST', '/api/v1/knowledge-bases/kb%2Fid/clone'],
      ['POST', '/api/v1/knowledge-bases/kb%2Fid/reindex'],
      ['PATCH', '/api/v1/documents/document%2Fid'],
      ['POST', '/api/v1/documents/document%2Fid/reindex'],
    ])
  })

  it('covers conversation management and model governance routes', async () => {
    await conversationApi.deleteConversation('conversation/id')
    await conversationApi.truncateConversation('conversation/id', 'message-1')
    await conversationApi.updateSettings('conversation/id', { top_k: 8 })
    await modelLifecycleApi.updateModelStatus('model/id', {
      status: 'APPROVED',
      reason: 'passed',
    })
    await modelLifecycleApi.rollbackModel('model/id', {
      scene: 'sentiment',
      environment: 'production',
      reason: 'regression',
    })
    await modelLifecycleApi.listDeployments({ environment: 'production' })
    await modelLifecycleApi.compareDeployments({ left_id: 'a', right_id: 'b' })

    expect(vi.mocked(requestData).mock.calls.map(([request]) => [request.method, request.url])).toEqual([
      ['DELETE', '/api/v1/conversations/conversation%2Fid'],
      ['POST', '/api/v1/conversations/conversation%2Fid/truncate'],
      ['PATCH', '/api/v1/conversations/conversation%2Fid/settings'],
      ['POST', '/api/v1/models/model%2Fid/status'],
      ['POST', '/api/v1/models/model%2Fid/rollback'],
      ['GET', '/api/v1/models/deployments'],
      ['GET', '/api/v1/models/deployments/compare'],
    ])
  })
})
