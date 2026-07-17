import { apiClient } from './client'

export interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  checks: Record<string, 'up' | 'down'>
}

export async function getReadiness(): Promise<ReadinessResponse> {
  const response = await apiClient.get<ReadinessResponse>('/health/ready', {
    skipAuthRefresh: true,
  })
  return response.data
}
