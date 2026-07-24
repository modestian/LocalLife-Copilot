<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { documentApi } from '@/api/documents'
import { getUserFacingError } from '@/api/errors'
import type {
  DocumentDetail,
  DocumentPreview,
  DocumentStatus,
  DocumentSummary,
} from '@/types/document'
import type { AcceptedTask, AsyncTaskDetail, TrackedTask } from '@/types/task'
import { formatFileSize } from '@/utils/document-upload'

import DocumentUploadPanel from './DocumentUploadPanel.vue'
import HighlightedText from './HighlightedText.vue'
import TaskProgressCard from './TaskProgressCard.vue'

const props = defineProps<{
  knowledgeBaseId: string
  defaultChunkSize: number
  defaultChunkOverlap: number
  canManage: boolean
}>()

const documents = ref<DocumentSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const status = ref<'' | Exclude<DocumentStatus, 'DELETED'>>('')
const loading = ref(false)
const listError = ref('')
const trackedTasks = ref<TrackedTask[]>(loadTrackedTasks(props.knowledgeBaseId))

const selected = ref<DocumentDetail | null>(null)
const preview = ref<DocumentPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const selectedVersion = ref<number | null>(null)
const previewTab = ref<'original' | 'chunks'>('original')
const keyword = ref('')
const previewChunkPage = ref(1)
const mutating = ref(false)
const mutationMessage = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const currentVersion = computed(() =>
  selected.value?.versions.find((version) => version.version_no === selectedVersion.value),
)

const statusLabels: Record<DocumentStatus, string> = {
  UPLOADED: '已上传',
  PARSING: '解析中',
  INDEXING: '索引中',
  READY: '已就绪',
  FAILED: '处理失败',
  ARCHIVED: '已归档',
  DELETED: '已删除',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

async function loadDocuments(resetPage = false): Promise<void> {
  if (resetPage) page.value = 1
  loading.value = true
  listError.value = ''
  try {
    const result = await documentApi.list(props.knowledgeBaseId, {
      page: page.value,
      page_size: pageSize,
      status: status.value || undefined,
    })
    documents.value = result.items
    total.value = result.total
  } catch (error) {
    documents.value = []
    total.value = 0
    listError.value = getUserFacingError(error, '文档列表加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function loadPreview(chunkPage = 1): Promise<void> {
  if (!selected.value || !selectedVersion.value) return
  previewLoading.value = true
  previewError.value = ''
  preview.value = null
  try {
    preview.value = await documentApi.preview(selected.value.id, {
      version_no: selectedVersion.value,
      keyword: keyword.value.trim() || undefined,
      chunk_page: chunkPage,
      chunk_page_size: 50,
    })
    previewChunkPage.value = preview.value.chunk_page
  } catch (error) {
    previewError.value = getUserFacingError(error, '文档预览加载失败，请稍后重试')
  } finally {
    previewLoading.value = false
  }
}

function changeChunkPage(next: number): void {
  if (next < 1 || !preview.value || next > Math.ceil(preview.value.chunk_total / preview.value.chunk_page_size)) return
  void loadPreview(next)
}

function submitPreviewSearch(): void {
  void loadPreview(1)
}

async function openDocument(document: DocumentSummary, preserveMutation = false): Promise<void> {
  selected.value = null
  preview.value = null
  previewError.value = ''
  previewChunkPage.value = 1
  if (!preserveMutation) mutationMessage.value = ''
  previewLoading.value = true
  try {
    const detail = await documentApi.get(document.id)
    selected.value = detail
    selectedVersion.value = detail.current_version_no
    await loadPreview()
  } catch (error) {
    previewError.value = getUserFacingError(error, '文档详情加载失败，请稍后重试')
  } finally {
    previewLoading.value = false
  }
}

function closePreview(): void {
  selected.value = null
  preview.value = null
  previewError.value = ''
}

async function changeVersion(): Promise<void> {
  mutationMessage.value = ''
  previewChunkPage.value = 1
  await loadPreview()
}

async function rollback(): Promise<void> {
  if (!selected.value || !selectedVersion.value || !props.canManage) return
  const versionNo = selectedVersion.value
  if (versionNo === selected.value.current_version_no) return
  if (!window.confirm(`确认将“${selected.value.display_name}”回滚到版本 ${versionNo}？回滚后会重建索引。`)) {
    return
  }

  mutating.value = true
  previewError.value = ''
  try {
    const accepted = await documentApi.rollback(selected.value.id, versionNo)
    trackTask(accepted)
    mutationMessage.value = `版本回滚任务已提交：${accepted.task_id}`
    const documentId = selected.value.id
    await loadDocuments()
    const summary = documents.value.find((item) => item.id === documentId)
    if (summary) await openDocument(summary, true)
  } catch (error) {
    previewError.value = getUserFacingError(error, '版本回滚提交失败，请稍后重试')
  } finally {
    mutating.value = false
  }
}

async function deleteDocument(): Promise<void> {
  if (!selected.value || !props.canManage) return
  if (!window.confirm(`确认逻辑删除“${selected.value.display_name}”？索引投影将异步移除。`)) return

  mutating.value = true
  previewError.value = ''
  try {
    const accepted = await documentApi.delete(selected.value.id)
    trackTask(accepted)
    mutationMessage.value = `删除任务已提交：${accepted.task_id}`
    closePreview()
    await loadDocuments()
  } catch (error) {
    previewError.value = getUserFacingError(error, '文档删除失败，请稍后重试')
  } finally {
    mutating.value = false
  }
}

function onUploadAccepted(task: AcceptedTask, files: File[]): void {
  trackTask(task, files.map((file) => file.name))
  void loadDocuments(true)
}

function trackTask(task: AcceptedTask, fileNames: string[] = []): void {
  trackedTasks.value = [
    { accepted: task, file_names: fileNames },
    ...trackedTasks.value.filter((item) => item.accepted.task_id !== task.task_id),
  ]
}

function loadTrackedTasks(kbId: string): TrackedTask[] {
  try {
    const raw = sessionStorage.getItem(`tracked-tasks:${kbId}`)
    if (!raw) return []
    const parsed: TrackedTask[] = JSON.parse(raw)
    // Only restore non-terminal tasks; terminal ones are no longer interesting
    return parsed.filter(
      (item) =>
        item.accepted &&
        item.accepted.task_id &&
        !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(item.accepted.status),
    )
  } catch {
    return []
  }
}

watch(trackedTasks, (tasks) => {
  try {
    sessionStorage.setItem(`tracked-tasks:${props.knowledgeBaseId}`, JSON.stringify(tasks))
  } catch { /* storage full – ignore */ }
}, { deep: true })

function onTaskTerminal(detail: AsyncTaskDetail): void {
  // Update stored status so sessionStorage reflects the terminal state
  const tracked = trackedTasks.value.find((t) => t.accepted.task_id === detail.task_id)
  if (tracked) {
    tracked.accepted.status = detail.status
    tracked.accepted.progress = detail.progress
  }
  void loadDocuments()
}

function previousPage(): void {
  if (page.value <= 1) return
  page.value -= 1
  void loadDocuments()
}

function nextPage(): void {
  if (page.value >= pageCount.value) return
  page.value += 1
  void loadDocuments()
}

onMounted(() => loadDocuments())
</script>

<template>
  <section class="document-workspace">
    <div class="workspace-title">
      <div>
        <span class="eyebrow">DOCUMENT LIFECYCLE</span>
        <h2>文档与版本</h2>
      </div>
      <span>上传、预览并恢复历史版本</span>
    </div>

    <DocumentUploadPanel
      :knowledge-base-id="knowledgeBaseId"
      :default-chunk-size="defaultChunkSize"
      :default-chunk-overlap="defaultChunkOverlap"
      :disabled="!canManage"
      @accepted="onUploadAccepted"
    />

    <section
      v-if="trackedTasks.length"
      class="task-tracker"
      aria-label="任务进度"
    >
      <div class="task-tracker__heading">
        <div>
          <span class="eyebrow">TASK TRACKING</span>
          <h3>任务进度</h3>
        </div>
        <span>自动刷新处理阶段与每个文件的状态</span>
      </div>
      <div class="task-tracker__list">
        <TaskProgressCard
          v-for="task in trackedTasks"
          :key="task.accepted.task_id"
          :task="task.accepted"
          :file-names="task.file_names"
          :can-manage="canManage"
          @terminal="onTaskTerminal"
        />
      </div>
    </section>

    <div class="document-list-heading">
      <div>
        <h3>文档列表</h3>
        <span>共 {{ total }} 个未删除文档</span>
      </div>
      <label>
        <span>状态</span>
        <select
          v-model="status"
          @change="loadDocuments(true)"
        >
          <option value="">全部状态</option>
          <option value="UPLOADED">已上传</option>
          <option value="PARSING">解析中</option>
          <option value="INDEXING">索引中</option>
          <option value="READY">已就绪</option>
          <option value="FAILED">处理失败</option>
          <option value="ARCHIVED">已归档</option>
        </select>
      </label>
    </div>

    <div
      v-if="loading"
      class="document-state"
    >
      正在加载文档…
    </div>
    <div
      v-else-if="listError"
      class="document-state is-error"
      role="alert"
    >
      <span>{{ listError }}</span>
      <button
        type="button"
        @click="loadDocuments()"
      >
        重试
      </button>
    </div>
    <div
      v-else-if="documents.length === 0"
      class="document-state"
    >
      当前筛选条件下暂无文档。
    </div>
    <div
      v-else
      class="document-table-wrap"
    >
      <table>
        <thead>
          <tr><th>文档</th><th>状态</th><th>当前版本</th><th>Chunk</th><th>更新时间</th><th /></tr>
        </thead>
        <tbody>
          <tr
            v-for="document in documents"
            :key="document.id"
          >
            <td>
              <strong>{{ document.display_name }}</strong>
              <span>{{ document.mime_type || document.source_type }} · {{ formatFileSize(document.file_size) }}</span>
            </td>
            <td>
              <span :class="['document-status', `is-${document.status.toLowerCase()}`]">
                {{ statusLabels[document.status] }}
              </span>
              <small v-if="document.last_error_code">{{ document.last_error_code }}</small>
            </td>
            <td>v{{ document.current_version_no }}</td>
            <td>{{ document.chunk_count }}</td>
            <td>{{ formatDate(document.updated_at) }}</td>
            <td>
              <button
                type="button"
                @click="openDocument(document)"
              >
                查看
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="total > pageSize"
      class="document-pagination"
    >
      <button
        type="button"
        :disabled="page <= 1"
        @click="previousPage"
      >
        上一页
      </button>
      <span>{{ page }} / {{ pageCount }}</span>
      <button
        type="button"
        :disabled="page >= pageCount"
        @click="nextPage"
      >
        下一页
      </button>
    </div>

    <div
      v-if="selected || previewLoading || previewError"
      class="preview-backdrop"
      @click.self="closePreview"
    >
      <aside
        class="preview-panel"
        aria-label="文档预览"
      >
        <header>
          <div>
            <span class="eyebrow">DOCUMENT PREVIEW</span>
            <h3>{{ selected?.display_name || '文档预览' }}</h3>
          </div>
          <button
            type="button"
            aria-label="关闭预览"
            @click="closePreview"
          >
            ×
          </button>
        </header>

        <div
          v-if="previewError"
          class="preview-error"
          role="alert"
        >
          {{ previewError }}
        </div>
        <div
          v-if="previewLoading"
          class="preview-loading"
        >
          正在读取版本与预览…
        </div>

        <template v-if="selected">
          <dl class="document-metadata">
            <div><dt>来源</dt><dd>{{ selected.source_key }}</dd></div>
            <div><dt>MIME</dt><dd>{{ selected.mime_type || '未记录' }}</dd></div>
            <div><dt>状态</dt><dd>{{ statusLabels[selected.status] }}</dd></div>
            <div><dt>更新时间</dt><dd>{{ formatDate(selected.updated_at) }}</dd></div>
          </dl>

          <section class="version-toolbar">
            <label>
              <span>查看版本</span>
              <select
                v-model="selectedVersion"
                @change="changeVersion"
              >
                <option
                  v-for="version in selected.versions"
                  :key="version.id"
                  :value="version.version_no"
                >
                  v{{ version.version_no }}{{ version.is_current ? '（当前）' : '' }}
                </option>
              </select>
            </label>
            <div v-if="currentVersion">
              <span>{{ formatFileSize(currentVersion.file_size) }}</span>
              <span>{{ currentVersion.parser_name }} {{ currentVersion.parser_version }}</span>
              <span :title="currentVersion.file_sha256">SHA-256 {{ currentVersion.file_sha256.slice(0, 12) }}…</span>
            </div>
            <button
              v-if="canManage && selectedVersion !== selected.current_version_no"
              class="button button--secondary"
              type="button"
              :disabled="mutating"
              @click="rollback"
            >
              回滚到此版本
            </button>
          </section>

          <p
            v-if="mutationMessage"
            class="mutation-message"
            role="status"
          >
            {{ mutationMessage }}
          </p>

          <div class="preview-controls">
            <div class="preview-tabs">
              <button
                type="button"
                :class="{ 'is-active': previewTab === 'original' }"
                @click="previewTab = 'original'"
              >
                原文
              </button>
              <button
                type="button"
                :class="{ 'is-active': previewTab === 'chunks' }"
                @click="previewTab = 'chunks'"
              >
                Chunk（{{ preview?.chunk_total ?? 0 }}）
              </button>
            </div>
            <form @submit.prevent="submitPreviewSearch">
              <input
                v-model="keyword"
                placeholder="输入关键词高亮"
              >
              <button type="submit">
                定位
              </button>
            </form>
          </div>

          <div
            v-if="preview && previewTab === 'original'"
            class="original-preview"
          >
            <HighlightedText
              :content="preview.original_content"
              :highlight="keyword"
            />
            <p v-if="preview.original_truncated">
              原文较长，当前仅展示服务端返回的截断内容。
            </p>
          </div>
          <ol
            v-else-if="preview && previewTab === 'chunks'"
            class="chunk-preview"
          >
            <li
              v-for="chunk in preview.chunks"
              :key="chunk.id"
            >
              <header>
                <strong>Chunk {{ chunk.chunk_no }}</strong>
                <span>{{ chunk.token_count }} tokens{{ chunk.page_number ? ` · 第 ${chunk.page_number} 页` : '' }}</span>
              </header>
              <p>
                <HighlightedText
                  :content="chunk.content"
                  :highlight="keyword"
                />
              </p>
            </li>
          </ol>

          <div
            v-if="preview && preview.chunk_total > preview.chunk_page_size"
            class="chunk-pagination"
          >
            <button
              type="button"
              :disabled="preview.chunk_page <= 1"
              @click="changeChunkPage(preview.chunk_page - 1)"
            >
              上一页
            </button>
            <span>{{ preview.chunk_page }} / {{ Math.ceil(preview.chunk_total / preview.chunk_page_size) }}</span>
            <button
              type="button"
              :disabled="preview.chunk_page >= Math.ceil(preview.chunk_total / preview.chunk_page_size)"
              @click="changeChunkPage(preview.chunk_page + 1)"
            >
              下一页
            </button>
          </div>

          <footer v-if="canManage">
            <button
              class="danger-button"
              type="button"
              :disabled="mutating"
              @click="deleteDocument"
            >
              逻辑删除文档
            </button>
          </footer>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.document-workspace { margin-top: 24px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 16px; padding: 24px; background: rgb(255 255 255 / 64%); }
.workspace-title { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 20px; color: #7b6d63; font-size: .78rem; }
.workspace-title h2 { margin: 8px 0 0; color: #2c211b; font-size: 1.45rem; }
.task-tracker { margin-top: 16px; border: 1px solid #dfd2c7; border-radius: 14px; padding: 18px; background: #faf4ec; }
.task-tracker__heading { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 12px; }
.task-tracker__heading h3 { margin: 6px 0 0; font-size: 1.1rem; }
.task-tracker__heading > span { color: #7b6d63; font-size: .72rem; }
.task-tracker__list { display: grid; gap: 10px; }
.document-list-heading { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-top: 28px; }
.document-list-heading h3 { margin: 0 0 4px; }
.document-list-heading div > span { color: #7b6d63; font-size: .74rem; }
.document-list-heading label { display: flex; gap: 8px; align-items: center; color: #695b51; font-size: .75rem; }
.document-list-heading select, .version-toolbar select, .preview-controls input { border: 1px solid #d9ccc1; border-radius: 8px; padding: 8px 10px; background: #fffdfa; color: #392d26; font: inherit; }
.document-state { margin-top: 14px; border: 1px dashed #d5c6b9; border-radius: 10px; padding: 28px 20px; color: #74645a; text-align: center; }
.document-state.is-error { border-color: #e3b3aa; background: #fff4f1; color: #8e3328; }
.document-state button { margin-left: 10px; border: 0; background: transparent; color: #9d3423; cursor: pointer; font-weight: 800; }
.document-table-wrap { margin-top: 14px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .78rem; }
th { border-bottom: 1px solid #dfd2c7; padding: 10px 9px; color: #7b6d63; font-size: .68rem; text-align: left; text-transform: uppercase; }
td { border-bottom: 1px solid #eadfd5; padding: 12px 9px; color: #4d3e35; vertical-align: middle; }
td:first-child { min-width: 210px; }
td:first-child strong, td:first-child span, td:nth-child(2) small { display: block; }
td:first-child span, td:nth-child(2) small { margin-top: 4px; color: #85746a; font-size: .67rem; }
td:last-child button { border: 0; background: transparent; color: #9d3423; cursor: pointer; font-weight: 800; }
.document-status { display: inline-flex; border-radius: 999px; padding: 4px 7px; background: #eee5dc; color: #695b51; font-size: .65rem; font-weight: 900; }
.document-status.is-ready { background: #e4f2e9; color: #2c704b; }
.document-status.is-failed { background: #f4dfdb; color: #9e3c30; }
.document-status.is-parsing, .document-status.is-indexing { background: #f8ecd5; color: #806226; }
.document-pagination { display: flex; justify-content: flex-end; gap: 10px; align-items: center; margin-top: 14px; color: #7b6d63; font-size: .72rem; }
.document-pagination button { border: 1px solid #d9ccc1; border-radius: 7px; padding: 6px 10px; background: #fffdfa; color: #6c5042; cursor: pointer; }
.document-pagination button:disabled { cursor: not-allowed; opacity: .45; }
.preview-backdrop { position: fixed; z-index: 50; inset: 0; display: flex; justify-content: flex-end; background: rgb(37 27 21 / 38%); backdrop-filter: blur(3px); }
.preview-panel { width: min(720px, 100%); height: 100%; padding: 26px; overflow: auto; background: #f9f5ee; box-shadow: -20px 0 60px rgb(43 31 24 / 18%); }
.preview-panel > header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; border-bottom: 1px solid #e0d4c9; padding-bottom: 18px; }
.preview-panel > header h3 { margin: 7px 0 0; font-size: 1.45rem; }
.preview-panel > header button { border: 0; background: transparent; color: #6d5c52; cursor: pointer; font-size: 1.7rem; }
.preview-loading, .preview-error { margin-top: 16px; border-radius: 9px; padding: 12px; color: #695b51; }
.preview-error { background: #fff0ed; color: #a4362b; }
.document-metadata { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; margin: 18px 0; }
.document-metadata div { display: grid; grid-template-columns: 75px 1fr; gap: 8px; border-bottom: 1px solid #e5d9ce; padding: 10px 0; font-size: .75rem; }
.document-metadata dt { color: #7b6d63; }
.document-metadata dd { margin: 0; overflow-wrap: anywhere; color: #3e3028; font-weight: 700; }
.version-toolbar { display: flex; gap: 12px; align-items: end; border-radius: 11px; padding: 14px; background: white; }
.version-toolbar label { display: grid; gap: 5px; color: #695b51; font-size: .7rem; font-weight: 800; }
.version-toolbar > div { display: flex; flex: 1; flex-wrap: wrap; gap: 5px 12px; color: #7b6d63; font-size: .68rem; }
.button { display: inline-flex; align-items: center; justify-content: center; min-height: 38px; border-radius: 8px; padding: 7px 12px; cursor: pointer; font-weight: 800; }
.button--secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.mutation-message { border-radius: 8px; padding: 9px 12px; background: #e4f2e9; color: #2c704b; font-size: .75rem; }
.preview-controls { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-top: 18px; }
.preview-tabs { display: flex; gap: 4px; border-radius: 9px; padding: 3px; background: #e9ded3; }
.preview-tabs button { border: 0; border-radius: 7px; padding: 7px 11px; background: transparent; color: #6c5b51; cursor: pointer; font: inherit; font-size: .72rem; font-weight: 800; }
.preview-tabs button.is-active { background: white; color: #9d3423; }
.preview-controls form { display: flex; }
.preview-controls form button { border: 1px solid #d9ccc1; border-left: 0; border-radius: 0 8px 8px 0; padding: 0 10px; background: #eee4da; color: #6c5042; cursor: pointer; font-weight: 800; }
.preview-controls input { border-radius: 8px 0 0 8px; }
.original-preview { margin-top: 12px; border: 1px solid #e1d5ca; border-radius: 12px; padding: 18px; background: white; color: #3f3129; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .78rem; line-height: 1.75; overflow-wrap: anywhere; white-space: pre-wrap; }
.original-preview p { color: #9d3423; font-family: inherit; }
.chunk-preview { display: grid; gap: 10px; margin: 12px 0 0; padding: 0; list-style: none; }
.chunk-preview li { border: 1px solid #e1d5ca; border-radius: 12px; padding: 15px; background: white; }
.chunk-preview header { display: flex; justify-content: space-between; gap: 12px; color: #8d3c2d; font-size: .7rem; }
.chunk-preview header span { color: #7b6d63; }
.chunk-preview p { margin: 10px 0 0; color: #42342c; font-size: .78rem; line-height: 1.7; white-space: pre-wrap; }
.preview-panel > footer { margin-top: 20px; border-top: 1px solid #e0d4c9; padding-top: 16px; text-align: right; }
.danger-button { border: 1px solid #d9a59c; border-radius: 8px; padding: 8px 12px; background: #fff1ee; color: #a4362b; cursor: pointer; font-weight: 800; }
.danger-button:disabled { cursor: not-allowed; opacity: .5; }
.chunk-pagination { display: flex; gap: 10px; align-items: center; justify-content: center; margin-top: 18px; font-size: .8rem; color: #695b51; }
.chunk-pagination button { min-width: 80px; }
@media (max-width: 760px) {
  .workspace-title, .document-list-heading, .task-tracker__heading, .preview-controls, .version-toolbar { align-items: stretch; flex-direction: column; }
  .document-metadata { grid-template-columns: 1fr; }
  .preview-panel { padding: 20px 14px; }
  .preview-controls form input { min-width: 0; width: 100%; }
}
</style>
