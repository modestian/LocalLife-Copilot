export type TaskStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'

export type TaskStage =
  | 'QUEUED'
  | 'LOADING'
  | 'CLEANING'
  | 'SPLITTING'
  | 'PERSISTING'
  | 'INDEXING'
  | 'VERIFYING'
  | 'DELETING'

export interface AcceptedTask {
  task_id: string
  status: TaskStatus
  progress: number
  status_url: string
}

export interface TaskFileProgress {
  file_name: string
  document_id: string | null
  status: TaskStatus | 'SKIPPED'
  stage: TaskStage | null
  progress: number
  error_code: string | null
  error_message: string | null
}

export interface AsyncTaskDetail {
  task_id: string
  task_type: string
  resource_type: string
  resource_id: string | null
  status: TaskStatus
  stage: TaskStage | null
  progress: number
  cancellable: boolean
  retryable: boolean
  attempt_count: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  files: TaskFileProgress[]
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TrackedTask {
  accepted: AcceptedTask
  file_names: string[]
}
