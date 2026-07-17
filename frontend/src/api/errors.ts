import axios from 'axios'

import type { ApiErrorResponse } from '@/types/api'

export class ApiClientError extends Error {
  readonly status?: number
  readonly code: string
  readonly details?: ApiErrorResponse['details']
  readonly requestId?: string

  constructor(options: {
    message: string
    code?: string
    status?: number
    details?: ApiErrorResponse['details']
    requestId?: string
    cause?: unknown
  }) {
    super(options.message, { cause: options.cause })
    this.name = 'ApiClientError'
    this.code = options.code ?? 'CLIENT_UNKNOWN_ERROR'
    this.status = options.status
    this.details = options.details
    this.requestId = options.requestId
  }
}

export function toApiClientError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error
  }

  if (!axios.isAxiosError<ApiErrorResponse>(error)) {
    return new ApiClientError({ message: '发生未知错误，请稍后重试', cause: error })
  }

  const responseData = error.response?.data
  return new ApiClientError({
    message: responseData?.message ?? (error.response ? '请求失败，请稍后重试' : '网络连接失败，请检查网络'),
    code: responseData?.code ?? (error.response ? 'HTTP_REQUEST_FAILED' : 'NETWORK_ERROR'),
    status: error.response?.status,
    details: responseData?.details,
    requestId: responseData?.request_id ?? error.response?.headers['x-request-id'],
    cause: error,
  })
}
