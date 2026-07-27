<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { taskApi } from '@/api/tasks'
import type {
  AcceptedTask,
  AsyncTaskDetail,
  TaskFileProgress,
  TaskStage,
  TaskStatus,
} from '@/types/task'

const props = withDefaults(defineProps<{
  task: AcceptedTask
  fileNames?: string[]
  canManage: boolean
  pollIntervalMs?: number
}>(), {
  fileNames: () => [],
  pollIntervalMs: 1500,
})

const emit = defineEmits<{
  terminal: [task: AsyncTaskDetail]
}>()

const activeTask = ref<AcceptedTask>({ ...props.task })
const detail = ref<AsyncTaskDetail | null>(null)
const loading = ref(false)
const acting = ref(false)
const errorMessage = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let requestVersion = 0

const terminalStatuses = new Set<TaskStatus>(['SUCCEEDED', 'FAILED', 'CANCELLED'])
const statusLabels: Record<TaskStatus | 'SKIPPED', string> = {
  PENDING: '等待处理',
  RUNNING: '处理中',
  SUCCEEDED: '处理成功',
  FAILED: '处理失败',
  CANCELLED: '已取消',
  SKIPPED: '已跳过',
}
const stageLabels: Record<TaskStage, string> = {
  QUEUED: '排队等待',
  LOADING: '读取与校验',
  CLEANING: '内容清洗',
  SPLITTING: '文档切分',
  PERSISTING: '持久化',
  INDEXING: '构建索引',
  VERIFYING: '结果校验',
  DELETING: '删除索引',
}

const status = computed(() => detail.value?.status ?? activeTask.value.status)
const progress = computed(() => detail.value?.progress ?? activeTask.value.progress)
const stage = computed(() => detail.value?.stage ?? (status.value === 'PENDING' ? 'QUEUED' : null))
const stageLabel = computed(() => stage.value ? stageLabels[stage.value] : '等待状态更新')
const isTerminal = computed(() => terminalStatuses.has(status.value))
const canCancel = computed(
  () =>
    props.canManage &&
    !acting.value &&
    !isTerminal.value &&
    (detail.value?.cancellable ?? status.value === 'PENDING'),
)
const canRetry = computed(
  () =>
    props.canManage &&
    !acting.value &&
    status.value === 'FAILED' &&
    detail.value?.retryable === true,
)
const fileProgress = computed<TaskFileProgress[]>(() => {
  if (detail.value?.files.length) return detail.value.files
  return props.fileNames.map((fileName) => ({
    file_name: fileName,
    document_id: null,
    status: activeTask.value.status,
    stage: activeTask.value.status === 'PENDING' ? 'QUEUED' : null,
    progress: activeTask.value.progress,
    error_code: null,
    error_message: null,
  }))
})

function clampProgress(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value)))
}

function schedulePoll(): void {
  clearPoll()
  if (isTerminal.value) return
  timer = setTimeout(() => void refresh(), props.pollIntervalMs)
}

function clearPoll(): void {
  if (timer) clearTimeout(timer)
  timer = undefined
}

async function refresh(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await taskApi.get(activeTask.value.task_id)
    if (version !== requestVersion) return
    detail.value = next
    activeTask.value = {
      task_id: next.task_id,
      status: next.status,
      progress: next.progress,
      status_url: `/api/v1/tasks/${next.task_id}`,
    }
    if (terminalStatuses.has(next.status)) emit('terminal', next)
  } catch (error) {
    if (version !== requestVersion) return
    errorMessage.value = getUserFacingError(error, '任务状态刷新失败，请稍后重试')
  } finally {
    if (version === requestVersion) {
      loading.value = false
      schedulePoll()
    }
  }
}

async function cancel(): Promise<void> {
  if (!canCancel.value) return
  requestVersion += 1
  acting.value = true
  errorMessage.value = ''
  clearPoll()
  try {
    activeTask.value = await taskApi.cancel(activeTask.value.task_id)
    detail.value = null
    await refresh()
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '取消任务失败，请稍后重试')
    schedulePoll()
  } finally {
    acting.value = false
  }
}

async function retry(): Promise<void> {
  if (!canRetry.value) return
  requestVersion += 1
  acting.value = true
  errorMessage.value = ''
  clearPoll()
  try {
    const accepted = await taskApi.retry(activeTask.value.task_id)
    activeTask.value = accepted
    detail.value = null
    await refresh()
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '重试任务提交失败，请稍后重试')
  } finally {
    acting.value = false
  }
}

onMounted(() => void refresh())
onBeforeUnmount(() => {
  requestVersion += 1
  clearPoll()
})
</script>

<template>
  <article :class="['task-card', `is-${status.toLowerCase()}`]">
    <header>
      <div>
        <span :class="['task-status', `is-${status.toLowerCase()}`]">
          {{ statusLabels[status] }}
        </span>
        <strong>{{ detail?.task_type || '文档处理任务' }}</strong>
        <small>{{ activeTask.task_id }}</small>
      </div>
      <button
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <div class="overall-progress">
      <div>
        <span>{{ stageLabel }}</span>
        <strong>{{ clampProgress(progress) }}%</strong>
      </div>
      <progress
        :value="clampProgress(progress)"
        max="100"
        :aria-label="`任务总进度 ${clampProgress(progress)}%`"
      />
    </div>

    <ul
      v-if="fileProgress.length"
      class="file-progress"
    >
      <li
        v-for="file in fileProgress"
        :key="`${file.document_id || ''}-${file.file_name}`"
        :class="{ 'has-error': file.status === 'FAILED' }"
      >
        <div>
          <strong>{{ file.file_name }}</strong>
          <span>{{ file.stage ? stageLabels[file.stage] : statusLabels[file.status] }}</span>
        </div>
        <progress
          :value="clampProgress(file.progress)"
          max="100"
          :aria-label="`${file.file_name} 进度 ${clampProgress(file.progress)}%`"
        />
        <span>{{ clampProgress(file.progress) }}%</span>
        <small v-if="file.error_code">{{ file.error_code }} · {{ file.error_message }}</small>
      </li>
    </ul>

    <section
      v-if="detail?.status === 'FAILED'"
      class="failure-detail"
      role="alert"
    >
      <strong>{{ detail.error_code || 'TASK_FAILED' }}</strong>
      <span>失败阶段：{{ detail.stage ? stageLabels[detail.stage] : '未知阶段' }}</span>
      <p>{{ detail.error_message || '任务处理失败，服务端未返回更多说明。' }}</p>
      <small>已尝试 {{ detail.attempt_count }} / {{ detail.max_attempts }} 次</small>
    </section>

    <p
      v-if="errorMessage"
      class="task-error"
      role="alert"
    >
      {{ errorMessage }}
    </p>

    <footer>
      <span v-if="detail && !detail.cancellable && !isTerminal">任务已进入不可中断阶段</span>
      <span v-else-if="detail?.updated_at">更新于 {{ new Date(detail.updated_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
      <div>
        <button
          v-if="!isTerminal"
          type="button"
          :disabled="!canCancel"
          @click="cancel"
        >
          {{ acting ? '处理中…' : '取消任务' }}
        </button>
        <button
          v-if="status === 'FAILED'"
          class="retry-button"
          type="button"
          :disabled="!canRetry"
          @click="retry"
        >
          {{ acting ? '提交中…' : detail?.retryable ? '重试任务' : '已达重试上限' }}
        </button>
      </div>
    </footer>
  </article>
</template>

<style scoped>
.task-card { border: 1px solid #dfd2c7; border-radius: 13px; padding: 16px; background: #fffdfa; }
.task-card.is-failed { border-color: #e3b3aa; background: #fff9f7; }
.task-card > header, .task-card > footer, .overall-progress > div, .file-progress li { display: flex; justify-content: space-between; gap: 14px; align-items: center; }
.task-card > header > div { display: flex; flex-wrap: wrap; gap: 7px 10px; align-items: center; min-width: 0; }
.task-card > header small { flex-basis: 100%; overflow: hidden; color: #86756b; font-size: .65rem; text-overflow: ellipsis; white-space: nowrap; }
.task-card > header button, .task-card > footer button { border: 1px solid #d9ccc1; border-radius: 7px; padding: 6px 10px; background: white; color: #6c5042; cursor: pointer; font-size: .7rem; font-weight: 800; }
.task-card button:disabled { cursor: not-allowed; opacity: .48; }
.task-status { display: inline-flex; border-radius: 999px; padding: 4px 7px; background: #eee5dc; color: #695b51; font-size: .64rem; font-weight: 900; }
.task-status.is-running { background: #f8ecd5; color: #806226; }
.task-status.is-succeeded { background: #e4f2e9; color: #2c704b; }
.task-status.is-failed { background: #f4dfdb; color: #9e3c30; }
.overall-progress { margin-top: 15px; }
.overall-progress span { color: #695b51; font-size: .74rem; font-weight: 800; }
.overall-progress strong { font-family: Georgia, serif; font-size: 1.1rem; }
progress { width: 100%; height: 8px; border: 0; border-radius: 999px; overflow: hidden; accent-color: var(--brand); }
progress::-webkit-progress-bar { border-radius: 999px; background: #eadfd5; }
progress::-webkit-progress-value { border-radius: 999px; background: var(--brand); }
.file-progress { display: grid; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none; }
.file-progress li { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(90px, 160px) 38px; border-top: 1px solid #eadfd5; padding-top: 9px; }
.file-progress li > div { display: grid; gap: 2px; min-width: 0; }
.file-progress li strong { overflow: hidden; font-size: .73rem; text-overflow: ellipsis; white-space: nowrap; }
.file-progress li span { color: #7b6d63; font-size: .66rem; }
.file-progress li > span { text-align: right; }
.file-progress li small { grid-column: 1 / -1; color: #a4362b; font-size: .66rem; }
.failure-detail { display: grid; gap: 5px; margin-top: 14px; border-left: 3px solid #b94334; border-radius: 8px; padding: 11px 13px; background: #fff0ed; color: #8e3328; font-size: .72rem; }
.failure-detail p { margin: 3px 0; line-height: 1.55; }
.task-error { margin: 12px 0 0; border-radius: 8px; padding: 9px 11px; background: #fff0ed; color: #a4362b; font-size: .72rem; }
.task-card > footer { align-items: end; margin-top: 14px; }
.task-card > footer > span { color: #85746a; font-size: .66rem; }
.task-card > footer > div { display: flex; gap: 8px; }
.task-card > footer .retry-button { border-color: var(--brand); background: var(--brand); color: white; }
@media (max-width: 620px) {
  .file-progress li { grid-template-columns: 1fr 40px; }
  .file-progress li progress { grid-column: 1 / -1; grid-row: 2; }
  .task-card > footer { align-items: stretch; flex-direction: column; }
  .task-card > footer > div { justify-content: flex-end; }
}
</style>
