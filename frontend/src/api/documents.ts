import type {
  AcceptedTask,
  DocumentDetail,
  DocumentListParams,
  DocumentPage,
  DocumentPreview,
  DocumentPreviewParams,
  UploadDocumentsPayload,
} from '@/types/document'

import { requestData } from './client'

function encoded(value: string): string {
  return encodeURIComponent(value)
}

export const documentApi = {
  list(knowledgeBaseId: string, params: DocumentListParams): Promise<DocumentPage> {
    return requestData({
      method: 'GET',
      url: `/api/v1/knowledge-bases/${encoded(knowledgeBaseId)}/documents`,
      params,
    })
  },

  upload(knowledgeBaseId: string, payload: UploadDocumentsPayload): Promise<AcceptedTask> {
    const form = new FormData()
    for (const file of payload.files) form.append('files[]', file, file.name)
    form.append('splitter', payload.splitter)
    form.append('chunk_size', String(payload.chunk_size))
    form.append('chunk_overlap', String(payload.chunk_overlap))
    form.append('force_new_version', String(payload.force_new_version))

    return requestData({
      method: 'POST',
      url: `/api/v1/knowledge-bases/${encoded(knowledgeBaseId)}/documents:upload`,
      data: form,
    })
  },

  get(documentId: string): Promise<DocumentDetail> {
    return requestData({ method: 'GET', url: `/api/v1/documents/${encoded(documentId)}` })
  },

  preview(documentId: string, params: DocumentPreviewParams): Promise<DocumentPreview> {
    return requestData({
      method: 'GET',
      url: `/api/v1/documents/${encoded(documentId)}/preview`,
      params,
    })
  },

  rollback(documentId: string, targetVersionNo: number): Promise<AcceptedTask> {
    return requestData({
      method: 'POST',
      url: `/api/v1/documents/${encoded(documentId)}/rollback`,
      data: { target_version_no: targetVersionNo },
    })
  },

  delete(documentId: string): Promise<AcceptedTask> {
    return requestData({ method: 'DELETE', url: `/api/v1/documents/${encoded(documentId)}` })
  },
}
