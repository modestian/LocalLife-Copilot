import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { modelLifecycleApi } from './model-lifecycle'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('model lifecycle API', () => {
  const requestId = '00000000-0000-4000-8000-000000000002'

  beforeEach(() => {
    vi.mocked(requestData).mockReset().mockResolvedValue({})
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId)
  })

  it('uses documented fine-tuning paths with idempotency keys', async () => {
    await modelLifecycleApi.createDataset({
      name: 'feedback-set',
      task_type: 'sentiment_classification',
      filters: { ratings: [-1], reviewed_only: true },
      split_config: { train_percent: 80, validation_percent: 10, test_percent: 10, isolation_key: 'CONVERSATION' },
    })
    await modelLifecycleApi.createJob({
      task_type: 'sentiment_classification',
      base_model_id: 'chinese-roberta-base',
      dataset_id: 'dataset/id',
      method: 'LORA',
      hyperparameters: { r: 8, lora_alpha: 16, lora_dropout: 0.05, learning_rate: 0.0002, epochs: 3, batch_size: 16, seed: 42 },
    })
    await modelLifecycleApi.evaluateJob('job/id')
    await modelLifecycleApi.registerModel('job/id')

    expect(requestData).toHaveBeenNthCalledWith(1, expect.objectContaining({
      method: 'POST',
      url: '/api/v1/fine-tuning/datasets',
      headers: { 'Idempotency-Key': requestId },
    }))
    expect(requestData).toHaveBeenNthCalledWith(2, expect.objectContaining({
      method: 'POST',
      url: '/api/v1/fine-tuning/jobs',
      headers: { 'Idempotency-Key': requestId },
    }))
    expect(requestData).toHaveBeenNthCalledWith(3, expect.objectContaining({
      url: '/api/v1/fine-tuning/jobs/job%2Fid/evaluate',
    }))
    expect(requestData).toHaveBeenNthCalledWith(4, expect.objectContaining({
      url: '/api/v1/fine-tuning/jobs/job%2Fid/register-model',
    }))
  })

  it('loads models and posts deployment metadata to the documented model endpoint', async () => {
    vi.mocked(requestData).mockResolvedValueOnce({ items: [{ id: 'model-1' }] }).mockResolvedValueOnce(undefined)

    await expect(modelLifecycleApi.listModels()).resolves.toEqual([{ id: 'model-1' }])
    await modelLifecycleApi.deployModel('model/id', {
      scene: 'merchant_analytics',
      environment: 'staging',
      traffic_percent: 10,
      reason: 'Canary validation',
    })

    expect(requestData).toHaveBeenLastCalledWith({
      method: 'POST',
      url: '/api/v1/models/model%2Fid/deploy',
      data: {
        scene: 'merchant_analytics',
        environment: 'staging',
        traffic_percent: 10,
        reason: 'Canary validation',
      },
      headers: { 'Idempotency-Key': requestId },
    })
  })
})
