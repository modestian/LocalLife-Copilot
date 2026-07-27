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

export function getUserFacingError(error: unknown, fallback = '操作失败，请稍后重试'): string {
  const apiError = toApiClientError(error)
  if (apiError.message) return apiError.message

  const statusMessages: Record<number, string> = {
    401: '登录状态已失效，请重新登录',
    403: '当前账号没有执行此操作的权限',
    404: '请求的内容不存在或无权访问',
    409: '数据状态已发生变化，请刷新后重试',
    422: '提交内容有误，请检查后重试',
    429: '操作过于频繁，请稍后重试',
    500: '服务暂时不可用，请稍后重试',
    502: '上游服务暂时不可用，请稍后重试',
    503: '服务正在恢复中，请稍后重试',
  }
  return (apiError.status && statusMessages[apiError.status]) || fallback
}

export function isAuthenticationError(error: unknown): boolean {
  const apiError = toApiClientError(error)
  return apiError.status === 401 || apiError.code.startsWith('AUTH_')
}
