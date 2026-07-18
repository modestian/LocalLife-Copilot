import type { AcceptedTask, AsyncTaskDetail } from '@/types/task'

import { requestData } from './client'

function encoded(value: string): string {
  return encodeURIComponent(value)
}

export const taskApi = {
  get(taskId: string): Promise<AsyncTaskDetail> {
    return requestData({ method: 'GET', url: `/api/v1/tasks/${encoded(taskId)}` })
  },

  cancel(taskId: string): Promise<AcceptedTask> {
    return requestData({ method: 'POST', url: `/api/v1/tasks/${encoded(taskId)}/cancel` })
  },

  retry(taskId: string): Promise<AcceptedTask> {
    return requestData({ method: 'POST', url: `/api/v1/tasks/${encoded(taskId)}/retry` })
  },
}
