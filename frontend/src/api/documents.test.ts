import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requestData } from './client'
import { documentApi } from './documents'

vi.mock('./client', () => ({ requestData: vi.fn() }))

describe('document API', () => {
  beforeEach(() => vi.mocked(requestData).mockReset().mockResolvedValue({}))

  it('uploads all files with the documented multipart fields', async () => {
    const files = [
      new File(['menu'], 'menu.csv', { type: 'text/csv' }),
      new File(['guide'], 'guide.md', { type: 'text/markdown' }),
    ]

    await documentApi.upload('kb/id', {
      files,
      splitter: 'recursive',
      chunk_size: 500,
      chunk_overlap: 80,
      cleaning_profile_id: 'clean-default',
      force_new_version: true,
    })

    const config = vi.mocked(requestData).mock.calls[0]?.[0]
    expect(config).toMatchObject({
      method: 'POST',
      url: '/api/v1/knowledge-bases/kb%2Fid/documents:upload',
    })
    const form = config?.data as FormData
    expect(form.getAll('files[]')).toEqual(files)
    expect(form.get('splitter')).toBe('recursive')
    expect(form.get('chunk_size')).toBe('500')
    expect(form.get('chunk_overlap')).toBe('80')
    expect(form.get('cleaning_profile_id')).toBe('clean-default')
    expect(form.get('force_new_version')).toBe('true')
  })

  it('uses the selected immutable version for preview and rollback', async () => {
    await documentApi.preview('document/id', { version_no: 2, keyword: '安静' })
    await documentApi.rollback('document/id', 2)

    expect(requestData).toHaveBeenNthCalledWith(1, {
      method: 'GET',
      url: '/api/v1/documents/document%2Fid/preview',
      params: { version_no: 2, keyword: '安静' },
    })
    expect(requestData).toHaveBeenNthCalledWith(2, {
      method: 'POST',
      url: '/api/v1/documents/document%2Fid/rollback',
      data: { target_version_no: 2 },
    })
  })

  it('uses DELETE so the server can apply logical deletion', async () => {
    await documentApi.delete('document-id')

    expect(requestData).toHaveBeenCalledWith({
      method: 'DELETE',
      url: '/api/v1/documents/document-id',
    })
  })
})
