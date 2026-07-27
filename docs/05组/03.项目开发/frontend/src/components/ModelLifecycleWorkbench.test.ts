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
    createModel: vi.fn(),
    updateModelStatus: vi.fn().mockResolvedValue({ ...approvedModel, status: 'APPROVED' }),
    deployModel: vi.fn().mockResolvedValue(undefined),
    rollbackModel: vi.fn().mockResolvedValue({
      id: 'deployment-1',
      model_version_id: 'model-1',
      scene: 'merchant_analytics',
      environment: 'staging',
      traffic_percent: 100,
      status: 'ACTIVE',
      action: 'ROLLBACK',
      result: 'SUCCEEDED',
    }),
    listDeployments: vi.fn().mockResolvedValue([{
      deployment_id: 'deployment-1',
      model_version_id: 'model-1',
      scene: 'merchant_analytics',
      environment: 'staging',
      traffic_percent: 100,
      status: 'ACTIVE',
    }]),
    compareDeployments: vi.fn(),
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

  it('submits human approval through the model status endpoint with a mandatory reason', async () => {
    const api = createApi()
    const evaluatedModel = { ...approvedModel, status: 'EVALUATED' as const }
    vi.mocked(api.listModels).mockResolvedValue([evaluatedModel])
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api, initialModels: [evaluatedModel] } })
    const approvalForm = wrapper.findAll('form')[3]
    const approveButton = approvalForm.get('button[type="submit"]')

    expect(approveButton.attributes('disabled')).toBeDefined()
    await approvalForm.get('textarea').setValue('固定集指标达标，人工抽检通过。')
    await approvalForm.get('input[type="checkbox"]').setValue(true)
    expect(approveButton.attributes('disabled')).toBeUndefined()
    await approvalForm.trigger('submit')
    await flushPromises()

    expect(api.updateModelStatus).toHaveBeenCalledWith('model-1', {
      status: 'APPROVED',
      reason: '固定集指标达标，人工抽检通过。',
    })
    expect(api.listModels).toHaveBeenCalled()
    expect(wrapper.text()).toContain('审批结论已提交')
  })

  it('rolls back through the documented endpoint and refreshes deployments and audit receipt', async () => {
    const api = createApi()
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api, initialModels: [approvedModel] } })
    const rollbackForm = wrapper.findAll('form')[4]
    const rollbackButton = rollbackForm.get('button[type="submit"]')

    expect(rollbackButton.attributes('disabled')).toBeDefined()
    await rollbackForm.get('textarea').setValue('灰度错误率超过阈值，执行回滚。')
    await rollbackForm.get('input[type="checkbox"]').setValue(true)
    expect(rollbackButton.attributes('disabled')).toBeUndefined()
    await rollbackForm.trigger('submit')
    await flushPromises()

    expect(api.rollbackModel).toHaveBeenCalledWith('model-1', {
      scene: 'merchant_analytics',
      environment: 'staging',
      reason: '灰度错误率超过阈值，执行回滚。',
    })
    expect(api.listModels).toHaveBeenCalled()
    expect(api.listDeployments).toHaveBeenCalledWith({ scene: 'merchant_analytics', environment: 'staging' })
    expect(wrapper.text()).toContain('最近回执：ROLLBACK / ACTIVE / SUCCEEDED')
    expect(wrapper.text()).toContain('回滚已执行')
  })

  it('keeps deployment disabled for a model that has not passed the APPROVED state', async () => {
    const api = createApi()
    const wrapper = mount(ModelLifecycleWorkbench, {
      props: { api, initialModels: [{ ...approvedModel, status: 'EVALUATED' }] },
    })
    const deploymentForm = wrapper.findAll('form')[2]
    const deployButton = deploymentForm.get('button[type="submit"]')

    await deploymentForm.get('textarea').setValue('未审批版本不得灰度发布。')
    await deploymentForm.get('input[type="checkbox"]').setValue(true)
    await deploymentForm.trigger('submit')

    expect(deployButton.attributes('disabled')).toBeDefined()
    expect(api.deployModel).not.toHaveBeenCalled()
  })

  it('renders the model-card empty state after an empty model-list response', async () => {
    const api = createApi()
    vi.mocked(api.listModels).mockResolvedValue([])
    const wrapper = mount(ModelLifecycleWorkbench, { props: { api } })

    await wrapper.get('.model-lifecycle__header button').trigger('click')
    await flushPromises()

    expect(wrapper.get('.model-lifecycle__empty').text()).toContain('加载模型列表')
    expect(wrapper.text()).toContain('当前没有可显示的模型版本')
  })
})
