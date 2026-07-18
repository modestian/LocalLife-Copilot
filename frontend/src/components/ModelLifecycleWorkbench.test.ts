import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { ModelLifecycleApi, ModelVersion, TrainingDataset } from '@/types/model-lifecycle'

import ModelLifecycleWorkbench from './ModelLifecycleWorkbench.vue'

const readyDataset: TrainingDataset = {
  id: 'dataset-1',
  name: '反馈情感数据集',
  task_type: 'sentiment_classification',
  dataset_hash: 'a'.repeat(64),
  redaction_version: 'pii-v2',
  sample_count: 1200,
  status: 'READY',
}

const approvedModel: ModelVersion = {
  id: 'model-1',
  name: '点评情感 LoRA',
  version: '1.2.0',
  task_type: 'sentiment_classification',
  status: 'APPROVED',
  base_model_ref: 'chinese-roberta-base',
  artifact_sha256: 'f'.repeat(64),
  metrics: { macro_f1: 0.86 },
  card: { dataset_hash: readyDataset.dataset_hash, limitations: ['仅适用于中文点评'] },
}

function createApi(): ModelLifecycleApi {
  return {
    createDataset: vi.fn(),
    getDataset: vi.fn().mockResolvedValue(readyDataset),
    createJob: vi.fn().mockResolvedValue({
      id: 'job-1', dataset_id: 'dataset-1', base_model_id: 'chinese-roberta-base', method: 'LORA',
      status: 'PENDING', progress: 0,
      hyperparameters: { r: 8, lora_alpha: 16, lora_dropout: 0.05, learning_rate: 0.0002, epochs: 3, batch_size: 16, seed: 42 },
    }),
    getJob: vi.fn(),
    cancelJob: vi.fn(),
    evaluateJob: vi.fn(),
    registerModel: vi.fn(),
    listModels: vi.fn().mockResolvedValue([approvedModel]),
    deployModel: vi.fn().mockResolvedValue(undefined),
  }
}

describe('ModelLifecycleWorkbench', () => {
  it('requires a READY immutable dataset before creating the documented LoRA job', async () => {
    const api = createApi()
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api } })

    await wrapper.get('.model-lifecycle__lookup input').setValue('dataset-1')
    await wrapper.get('.model-lifecycle__lookup button').trigger('click')
    await flushPromises()
    await wrapper.findAll('form')[1].trigger('submit')
    await flushPromises()

    expect(api.createJob).toHaveBeenCalledWith({
      task_type: 'sentiment_classification',
      base_model_id: 'chinese-roberta-base',
      dataset_id: 'dataset-1',
      method: 'LORA',
      hyperparameters: { r: 8, lora_alpha: 16, lora_dropout: 0.05, learning_rate: 0.0002, epochs: 3, batch_size: 16, seed: 42 },
    })
    expect(wrapper.text()).toContain('训练任务已创建')
  })

  it('only enables deployment for an approved model after explicit confirmation', async () => {
    const api = createApi()
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api, initialModels: [approvedModel] } })
    const deploymentForm = wrapper.findAll('form')[2]
    const deployButton = deploymentForm.get('button[type="submit"]')

    expect(deployButton.attributes('disabled')).toBeDefined()
    await deploymentForm.get('textarea').setValue('验证 10% 灰度的错误率与回滚路径。')
    await deploymentForm.get('input[type="checkbox"]').setValue(true)
    expect(deployButton.attributes('disabled')).toBeUndefined()
    await deploymentForm.trigger('submit')
    await flushPromises()

    expect(api.deployModel).toHaveBeenCalledWith('model-1', {
      scene: 'merchant_analytics',
      environment: 'staging',
      traffic_percent: 10,
      reason: '验证 10% 灰度的错误率与回滚路径。',
    })
  })

  it('does not fabricate approval or rollback state without a documented endpoint', async () => {
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api: createApi(), initialModels: [approvedModel] } })

    await wrapper.findAll('.model-lifecycle__actions button').at(-1)?.trigger('click')

    expect(wrapper.text()).toContain('回滚接口尚未在 API 文档中定义')
  })
})
