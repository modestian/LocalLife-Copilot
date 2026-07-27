import { ref } from 'vue'
import { defineStore } from 'pinia'

import { knowledgeBaseApi } from '@/api/knowledge-bases'
import { getUserFacingError } from '@/api/errors'
import type {
  CreateKnowledgeBasePayload,
  KnowledgeBaseDetail,
  KnowledgeBaseListParams,
  KnowledgeBaseSummary,
  UpdateKnowledgeBasePayload,
} from '@/types/knowledge-base'

const defaultPageSize = 10

export const useKnowledgeBaseStore = defineStore('knowledge-base', () => {
  const items = ref<KnowledgeBaseSummary[]>([])
  const detail = ref<KnowledgeBaseDetail | null>(null)
  const page = ref(1)
  const pageSize = ref(defaultPageSize)
  const total = ref(0)
  const loading = ref(false)
  const saving = ref(false)
  const errorMessage = ref('')
  let listRequest = 0

  async function loadList(params: KnowledgeBaseListParams): Promise<void> {
    const request = ++listRequest
    loading.value = true
    errorMessage.value = ''
    try {
      const result = await knowledgeBaseApi.list(params)
      if (request !== listRequest) return
      items.value = result.items
      page.value = result.page
      pageSize.value = result.page_size
      total.value = result.total
    } catch (error) {
      if (request !== listRequest) return
      items.value = []
      total.value = 0
      errorMessage.value = getUserFacingError(error, '知识库列表加载失败，请稍后重试')
    } finally {
      if (request === listRequest) loading.value = false
    }
  }

  async function loadDetail(id: string): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    detail.value = null
    try {
      detail.value = await knowledgeBaseApi.get(id)
    } catch (error) {
      errorMessage.value = getUserFacingError(error, '知识库详情加载失败，请稍后重试')
    } finally {
      loading.value = false
    }
  }

  async function updateDetail(
    id: string,
    payload: UpdateKnowledgeBasePayload,
  ): Promise<KnowledgeBaseDetail> {
    saving.value = true
    errorMessage.value = ''
    try {
      const updated = await knowledgeBaseApi.update(id, payload)
      detail.value = updated
      const index = items.value.findIndex((item) => item.id === id)
      if (index >= 0) items.value[index] = updated
      return updated
    } catch (error) {
      errorMessage.value = getUserFacingError(error, '知识库保存失败，请稍后重试')
      throw error
    } finally {
      saving.value = false
    }
  }

  async function createKnowledgeBase(
    payload: CreateKnowledgeBasePayload,
  ): Promise<KnowledgeBaseDetail> {
    saving.value = true
    errorMessage.value = ''
    try {
      const created = await knowledgeBaseApi.create(payload)
      return created
    } catch (error) {
      errorMessage.value = getUserFacingError(error, '知识库创建失败，请稍后重试')
      throw error
    } finally {
      saving.value = false
    }
  }

  async function deleteKnowledgeBase(
    id: string,
    purge = false,
  ): Promise<void> {
    saving.value = true
    errorMessage.value = ''
    try {
      await knowledgeBaseApi.delete(id, purge)
      items.value = items.value.filter((item) => item.id !== id)
      if (detail.value?.id === id) detail.value = null
    } catch (error) {
      errorMessage.value = getUserFacingError(error, '知识库删除失败，请稍后重试')
      throw error
    } finally {
      saving.value = false
    }
  }

  return {
    items,
    detail,
    page,
    pageSize,
    total,
    loading,
    saving,
    errorMessage,
    loadList,
    loadDetail,
    updateDetail,
    createKnowledgeBase,
    deleteKnowledgeBase,
  }
})
