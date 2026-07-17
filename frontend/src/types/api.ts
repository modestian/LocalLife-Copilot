export interface ApiResponse<T> {
  code: string
  message: string
  data: T
  request_id: string
}

export interface ApiErrorDetail {
  field?: string
  reason: string
  [key: string]: unknown
}

export interface ApiErrorResponse {
  code: string
  message: string
  details?: ApiErrorDetail[]
  request_id?: string
}

export interface PageResult<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}
