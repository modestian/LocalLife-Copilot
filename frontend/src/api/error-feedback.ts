import { ElMessage } from 'element-plus'

import { getUserFacingError } from './errors'

export function notifyApiError(error: unknown, fallback?: string): void {
  ElMessage.error({
    message: getUserFacingError(error, fallback),
    grouping: true,
    showClose: true,
  })
}
