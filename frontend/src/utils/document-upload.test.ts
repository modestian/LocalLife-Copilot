import { describe, expect, it } from 'vitest'

import {
  MAX_UPLOAD_FILE_BYTES,
  MAX_UPLOAD_FILE_COUNT,
  validateUploadCount,
  validateUploadFiles,
} from './document-upload'

describe('document upload validation', () => {
  it('accepts every ETL-supported extension with a matching MIME', () => {
    const files = [
      new File(['text'], 'notes.txt', { type: 'text/plain' }),
      new File(['markdown'], 'guide.md', { type: 'text/markdown' }),
      new File(['pdf'], 'menu.pdf', { type: 'application/pdf' }),
      new File(['docx'], 'intro.docx', {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      }),
      new File(['csv'], 'shops.csv', { type: 'text/csv' }),
      new File(['xlsx'], 'shops.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
    ]

    expect(validateUploadFiles(files).every((result) => result.valid)).toBe(true)
  })

  it('reports unsupported formats, mismatched MIME, empty and duplicate files', () => {
    const files = [
      new File(['payload'], 'script.exe', { type: 'application/octet-stream' }),
      new File(['not pdf'], 'menu.pdf', { type: 'text/plain' }),
      new File([], 'empty.txt', { type: 'text/plain' }),
      new File(['same'], 'duplicate.md', { type: 'text/markdown' }),
      new File(['same'], 'duplicate.md', { type: 'text/markdown' }),
    ]
    const results = validateUploadFiles(files)

    expect(results[0]?.errors).toContain('不支持 .exe 格式')
    expect(results[1]?.errors[0]).toContain('MIME text/plain')
    expect(results[2]?.errors).toContain('文件内容为空')
    expect(results[3]?.errors).toContain('文件名和大小重复')
    expect(results[4]?.errors).toContain('文件名和大小重复')
  })

  it('enforces file size and batch count limits', () => {
    const oversized = new File(['x'], 'large.txt', { type: 'text/plain' })
    Object.defineProperty(oversized, 'size', { value: MAX_UPLOAD_FILE_BYTES + 1 })
    const tooMany = Array.from(
      { length: MAX_UPLOAD_FILE_COUNT + 1 },
      (_, index) => new File(['x'], `${index}.txt`, { type: 'text/plain' }),
    )

    expect(validateUploadFiles([oversized])[0]?.errors).toContain('文件超过 100 MB')
    expect(validateUploadCount(tooMany)).toBe(`单次最多上传 ${MAX_UPLOAD_FILE_COUNT} 个文件`)
  })
})
