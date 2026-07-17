export const MAX_UPLOAD_FILE_COUNT = 20
export const MAX_UPLOAD_FILE_BYTES = 100 * 1024 * 1024

export const acceptedDocumentExtensions = ['.txt', '.md', '.pdf', '.docx', '.csv', '.xlsx'] as const

const acceptedMimeTypes: Record<(typeof acceptedDocumentExtensions)[number], ReadonlySet<string>> = {
  '.txt': new Set(['text/plain']),
  '.md': new Set(['text/markdown', 'text/plain', 'text/x-markdown']),
  '.pdf': new Set(['application/pdf']),
  '.docx': new Set([
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ]),
  '.csv': new Set(['text/csv', 'text/plain', 'application/csv', 'application/vnd.ms-excel']),
  '.xlsx': new Set(['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']),
}

export interface UploadFileValidation {
  file: File
  valid: boolean
  errors: string[]
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

export function formatFileSize(bytes: number | null): string {
  if (bytes === null) return '未知大小'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function validateUploadFiles(files: File[]): UploadFileValidation[] {
  const duplicateKeys = new Map<string, number>()
  for (const file of files) {
    const key = `${file.name.toLocaleLowerCase()}\u0000${file.size}`
    duplicateKeys.set(key, (duplicateKeys.get(key) ?? 0) + 1)
  }

  return files.map((file) => {
    const errors: string[] = []
    const extension = extensionOf(file.name)
    const isAcceptedExtension = acceptedDocumentExtensions.includes(
      extension as (typeof acceptedDocumentExtensions)[number],
    )

    if (!isAcceptedExtension) {
      errors.push(`不支持 ${extension || '无扩展名'} 格式`)
    } else if (file.type && !acceptedMimeTypes[extension as keyof typeof acceptedMimeTypes].has(file.type)) {
      errors.push(`MIME ${file.type} 与文件格式不匹配`)
    }
    if (file.size === 0) errors.push('文件内容为空')
    if (file.size > MAX_UPLOAD_FILE_BYTES) errors.push('文件超过 100 MB')
    if ((duplicateKeys.get(`${file.name.toLocaleLowerCase()}\u0000${file.size}`) ?? 0) > 1) {
      errors.push('文件名和大小重复')
    }

    return { file, valid: errors.length === 0, errors }
  })
}

export function validateUploadCount(files: File[]): string | null {
  if (files.length === 0) return '请至少选择一个文件'
  if (files.length > MAX_UPLOAD_FILE_COUNT) return `单次最多上传 ${MAX_UPLOAD_FILE_COUNT} 个文件`
  return null
}
