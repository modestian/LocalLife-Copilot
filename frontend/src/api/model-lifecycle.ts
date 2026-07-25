import type {
  CreateFineTuningJobRequest,
  DatasetBuildRequest,
  FineTuningJob,
  ModelDeploymentRequest,
  ModelDeployment,
  ModelLifecycleApi,
  ModelRegistrationRequest,
  ModelRollbackRequest,
  ModelStatusRequest,
  ModelVersion,
  TrainingDataset,
} from '@/types/model-lifecycle'

import { requestData } from './client'

interface ModelListResponse {
  items: ModelVersion[]
}

function encoded(id: string): string {
  return encodeURIComponent(id)
}

function idempotencyHeaders(): Record<string, string> {
  return { 'Idempotency-Key': crypto.randomUUID() }
}

export const modelLifecycleApi: ModelLifecycleApi = {
  createDataset(payload: DatasetBuildRequest): Promise<TrainingDataset> {
    return requestData({
      method: 'POST',
      url: '/api/v1/fine-tuning/datasets',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  getDataset(datasetId: string): Promise<TrainingDataset> {
    return requestData({ method: 'GET', url: `/api/v1/fine-tuning/datasets/${encoded(datasetId)}` })
  },

  createJob(payload: CreateFineTuningJobRequest): Promise<FineTuningJob> {
    return requestData({
      method: 'POST',
      url: '/api/v1/fine-tuning/jobs',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  getJob(jobId: string): Promise<FineTuningJob> {
    return requestData({ method: 'GET', url: `/api/v1/fine-tuning/jobs/${encoded(jobId)}` })
  },

  cancelJob(jobId: string): Promise<FineTuningJob> {
    return requestData({
      method: 'POST',
      url: `/api/v1/fine-tuning/jobs/${encoded(jobId)}/cancel`,
      headers: idempotencyHeaders(),
    })
  },

  evaluateJob(jobId: string): Promise<FineTuningJob> {
    return requestData({
      method: 'POST',
      url: `/api/v1/fine-tuning/jobs/${encoded(jobId)}/evaluate`,
      headers: idempotencyHeaders(),
    })
  },

  registerModel(jobId: string): Promise<ModelVersion> {
    return requestData({
      method: 'POST',
      url: `/api/v1/fine-tuning/jobs/${encoded(jobId)}/register-model`,
      headers: idempotencyHeaders(),
    })
  },

  async listModels(): Promise<ModelVersion[]> {
    const data = await requestData<ModelListResponse | ModelVersion[]>({
      method: 'GET',
      url: '/api/v1/models',
    })
    return Array.isArray(data) ? data : data.items
  },

  createModel(payload: ModelRegistrationRequest): Promise<ModelVersion> {
    return requestData({
      method: 'POST',
      url: '/api/v1/models',
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  updateModelStatus(modelId: string, payload: ModelStatusRequest): Promise<ModelVersion> {
    return requestData({
      method: 'POST',
      url: `/api/v1/models/${encoded(modelId)}/status`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  deployModel(modelId: string, payload: ModelDeploymentRequest): Promise<void> {
    return requestData({
      method: 'POST',
      url: `/api/v1/models/${encoded(modelId)}/deploy`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  rollbackModel(modelId: string, payload: ModelRollbackRequest): Promise<ModelDeployment> {
    return requestData({
      method: 'POST',
      url: `/api/v1/models/${encoded(modelId)}/rollback`,
      data: payload,
      headers: idempotencyHeaders(),
    })
  },

  async listDeployments(params: Record<string, string> = {}): Promise<ModelDeployment[]> {
    const data = await requestData<{ items: ModelDeployment[] } | ModelDeployment[]>({
      method: 'GET',
      url: '/api/v1/models/deployments',
      params,
    })
    return Array.isArray(data) ? data : data.items
  },

  compareDeployments(params: Record<string, string>): Promise<Record<string, unknown>> {
    return requestData({
      method: 'GET',
      url: '/api/v1/models/deployments/compare',
      params,
    })
  },
}
