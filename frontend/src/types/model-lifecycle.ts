export type DatasetStatus = 'BUILDING' | 'READY' | 'REJECTED' | 'ARCHIVED'
export type FineTuningJobStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
export type ModelVersionStatus = 'REGISTERED' | 'EVALUATED' | 'APPROVED' | 'REJECTED' | 'ARCHIVED'
export type FineTuningMethod = 'LORA' | 'QLORA'

export interface DatasetFilter {
  ratings?: Array<-1 | 1>
  task_type?: string
  reviewed_only?: boolean
  created_from?: string
  created_to?: string
}

export interface DatasetBuildRequest {
  name: string
  task_type: string
  filters: DatasetFilter
  split_config: {
    train_percent: number
    validation_percent: number
    test_percent: number
    isolation_key: 'CONVERSATION' | 'ENTITY'
  }
}

export interface TrainingDataset {
  id: string
  name: string
  task_type: string
  dataset_hash: string
  storage_uri?: string
  redaction_version: string
  sample_count: number
  status: DatasetStatus
  filter_config?: Record<string, unknown>
  split_config?: Record<string, unknown>
  statistics?: Record<string, unknown>
  quality_report?: Record<string, unknown>
  created_at?: string
}

export interface FineTuningHyperparameters {
  r: number
  lora_alpha: number
  lora_dropout: number
  learning_rate: number
  epochs: number
  batch_size: number
  seed: number
}

export interface CreateFineTuningJobRequest {
  task_type: string
  base_model_id: string
  dataset_id: string
  method: FineTuningMethod
  hyperparameters: FineTuningHyperparameters
}

export interface FineTuningJob {
  id: string
  dataset_id: string
  base_model_id: string
  method: FineTuningMethod
  status: FineTuningJobStatus
  progress: number
  hyperparameters: FineTuningHyperparameters
  logs_uri?: string | null
  artifact_uri?: string | null
  metrics?: Record<string, number | string | null> | null
  error_code?: string | null
  error_message?: string | null
  created_at?: string
  updated_at?: string
}

export interface ModelCard {
  dataset_hash?: string
  base_model_ref?: string
  method?: FineTuningMethod
  metrics?: Record<string, number | string | null>
  limitations?: string[]
  human_review_summary?: string
}

export interface ModelVersion {
  id: string
  name: string
  version: string
  task_type: string
  status: ModelVersionStatus
  base_model_ref: string
  adapter_uri?: string | null
  artifact_sha256?: string | null
  metrics?: Record<string, number | string | null>
  card?: ModelCard | null
}

export interface ModelDeploymentRequest {
  scene: string
  environment: string
  traffic_percent: number
  reason: string
}

export interface ModelRegistrationRequest {
  code: string
  name: string
  task_type: string
  provider: string
  version: string
  base_model_ref: string
  adapter_uri: string
  artifact_sha256: string
  dimension?: number | null
  labels?: string[] | null
  metrics?: Record<string, unknown> | null
}

export interface ModelStatusRequest {
  status: Exclude<ModelVersionStatus, 'REGISTERED'>
  reason: string
}

export interface ModelRollbackRequest {
  scene: string
  environment: string
  reason: string
}

export interface ModelDeployment {
  id: string
  model_version_id: string
  scene: string
  environment: string
  traffic_percent: number
  status: string
  created_at?: string
}

export interface ModelLifecycleApi {
  createDataset: (payload: DatasetBuildRequest) => Promise<TrainingDataset>
  getDataset: (datasetId: string) => Promise<TrainingDataset>
  createJob: (payload: CreateFineTuningJobRequest) => Promise<FineTuningJob>
  getJob: (jobId: string) => Promise<FineTuningJob>
  cancelJob: (jobId: string) => Promise<FineTuningJob>
  evaluateJob: (jobId: string) => Promise<FineTuningJob>
  registerModel: (jobId: string) => Promise<ModelVersion>
  listModels: () => Promise<ModelVersion[]>
  createModel: (payload: ModelRegistrationRequest) => Promise<ModelVersion>
  updateModelStatus: (modelId: string, payload: ModelStatusRequest) => Promise<ModelVersion>
  deployModel: (modelId: string, payload: ModelDeploymentRequest) => Promise<void>
  rollbackModel: (modelId: string, payload: ModelRollbackRequest) => Promise<ModelDeployment>
  listDeployments: (params?: Record<string, string>) => Promise<ModelDeployment[]>
  compareDeployments: (params: Record<string, string>) => Promise<Record<string, unknown>>
}
