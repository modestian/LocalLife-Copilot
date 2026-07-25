<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import { documentApi } from '@/api/documents'
import { getUserFacingError } from '@/api/errors'
import type { DocumentImportMode, SplitterStrategy, UploadResult } from '@/types/document'
import {
  acceptedDocumentExtensions,
  formatFileSize,
  MAX_UPLOAD_FILE_COUNT,
  validateUploadCount,
  validateUploadFiles,
} from '@/utils/document-upload'

const props = defineProps<{
  knowledgeBaseId: string
  defaultChunkSize: number
  defaultChunkOverlap: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  accepted: [task: UploadResult, files: File[]]
}>()

const input = ref<HTMLInputElement | null>(null)
const files = ref<File[]>([])
const dragging = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const options = reactive({
  importMode: 'knowledge' as DocumentImportMode,
  splitter: 'recursive' as SplitterStrategy,
  chunkSize: props.defaultChunkSize,
  chunkOverlap: props.defaultChunkOverlap,
  forceNewVersion: false,
})

const validations = computed(() => validateUploadFiles(files.value))
const countError = computed(() => validateUploadCount(files.value))
const invalidCount = computed(() => validations.value.filter((item) => !item.valid).length)
const canSubmit = computed(
  () =>
    !props.disabled &&
    !submitting.value &&
    !countError.value &&
    invalidCount.value === 0 &&
    options.chunkSize >= 100 &&
    options.chunkSize <= 4000 &&
    options.chunkOverlap >= 0 &&
    options.chunkOverlap < options.chunkSize,
)

function addFiles(next: File[]): void {
  errorMessage.value = ''
  files.value = [...files.value, ...next]
}

function onSelect(event: Event): void {
  const target = event.target as HTMLInputElement
  addFiles(Array.from(target.files ?? []))
  target.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (props.disabled) return
  addFiles(Array.from(event.dataTransfer?.files ?? []))
}

function removeFile(index: number): void {
  files.value = files.value.filter((_, itemIndex) => itemIndex !== index)
}

function clearFiles(): void {
  files.value = []
  errorMessage.value = ''
}

async function submit(): Promise<void> {
  errorMessage.value = ''
  if (countError.value) {
    errorMessage.value = countError.value
    return
  }
  if (invalidCount.value > 0) {
    errorMessage.value = '请移除或更换校验失败的文件。'
    return
  }
  if (options.chunkSize < 100 || options.chunkSize > 4000) {
    errorMessage.value = 'Chunk 大小必须在 100—4000 之间。'
    return
  }
  if (options.chunkOverlap < 0 || options.chunkOverlap >= options.chunkSize) {
    errorMessage.value = '重叠长度必须不小于 0 且小于 Chunk 大小。'
    return
  }

  submitting.value = true
  try {
    const acceptedFiles = [...files.value]
    const task = await documentApi.upload(props.knowledgeBaseId, {
      files: acceptedFiles,
      splitter: options.splitter,
      chunk_size: options.chunkSize,
      chunk_overlap: options.chunkOverlap,
      force_new_version: options.forceNewVersion,
      import_mode: options.importMode,
    })
    files.value = []
    emit('accepted', task, acceptedFiles)
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '文档上传失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="upload-panel">
    <div class="upload-panel__heading">
      <div>
        <span class="eyebrow">BATCH UPLOAD</span>
        <h3>上传与切分</h3>
      </div>
      <span>最多 {{ MAX_UPLOAD_FILE_COUNT }} 个文件 · 单个不超过 100 MB</span>
    </div>

    <button
      class="drop-zone"
      :class="{ 'is-dragging': dragging, 'is-disabled': disabled }"
      type="button"
      :disabled="disabled"
      @click="input?.click()"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <strong>{{ disabled ? '当前账号不可上传文档' : '拖放文件到这里，或点击选择' }}</strong>
      <span>{{ acceptedDocumentExtensions.join('、') }}</span>
    </button>
    <input
      ref="input"
      class="visually-hidden"
      type="file"
      multiple
      :accept="acceptedDocumentExtensions.join(',')"
      :disabled="disabled"
      @change="onSelect"
    >

    <div
      v-if="files.length"
      class="selected-files"
    >
      <div class="selected-files__summary">
        <strong>待上传 {{ files.length }} 个</strong>
        <span :class="{ 'has-errors': invalidCount > 0 || Boolean(countError) }">
          {{ countError || (invalidCount ? `${invalidCount} 个未通过校验` : '全部通过预检') }}
        </span>
        <button
          type="button"
          @click="clearFiles"
        >
          清空
        </button>
      </div>
      <ul>
        <li
          v-for="(item, index) in validations"
          :key="`${item.file.name}-${item.file.size}-${index}`"
          :class="{ 'is-invalid': !item.valid }"
        >
          <div>
            <strong>{{ item.file.name }}</strong>
            <span>{{ formatFileSize(item.file.size) }} · {{ item.file.type || '浏览器未提供 MIME' }}</span>
            <small v-if="item.errors.length">{{ item.errors.join('；') }}</small>
            <small v-else>格式、MIME 与大小校验通过</small>
          </div>
          <button
            type="button"
            :aria-label="`移除 ${item.file.name}`"
            @click="removeFile(index)"
          >
            移除
          </button>
        </li>
      </ul>
    </div>

    <div class="upload-options">
      <label>
        <span>上传类型</span>
        <select v-model="options.importMode">
          <option value="knowledge">知识文档</option>
          <option value="merchant_reviews">商家评论数据</option>
        </select>
      </label>
      <label>
        <span>切分策略</span>
        <select v-model="options.splitter">
          <option value="recursive">递归切分</option>
          <option value="semantic">语义切分</option>
        </select>
      </label>
      <label>
        <span>Chunk 大小</span>
        <input
          v-model.number="options.chunkSize"
          type="number"
          min="100"
          max="4000"
        >
      </label>
      <label>
        <span>重叠长度</span>
        <input
          v-model.number="options.chunkOverlap"
          type="number"
          min="0"
          :max="Math.max(0, options.chunkSize - 1)"
        >
      </label>
      <label class="checkbox-option">
        <input
          v-model="options.forceNewVersion"
          type="checkbox"
        >
        <span>重复文件强制创建新版本</span>
      </label>
    </div>
    <p
      v-if="options.importMode === 'merchant_reviews'"
      class="upload-hint"
    >
      仅支持符合项目导入规范的 CSV/XLSX；成功后会同步写入商家、评论和检索索引。
    </p>

    <p
      v-if="errorMessage"
      class="upload-error"
      role="alert"
    >
      {{ errorMessage }}
    </p>
    <div class="upload-actions">
      <span>服务器仍会重新校验文件内容与 SHA-256。</span>
      <button
        class="button button--primary"
        type="button"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ submitting ? '正在提交…' : files.length ? `提交 ${files.length} 个文件` : '提交文件' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.upload-panel { border: 1px solid #eadfd5; border-radius: 14px; padding: 20px; background: #fffdfa; }
.upload-panel__heading { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 16px; }
.upload-panel__heading h3 { margin: 6px 0 0; font-size: 1.2rem; }
.upload-panel__heading > span { color: #7b6d63; font-size: .74rem; }
.drop-zone { display: grid; gap: 7px; width: 100%; border: 1px dashed #cdb6a6; border-radius: 12px; padding: 28px 20px; background: #faf4ec; color: #5f493c; cursor: pointer; text-align: center; }
.drop-zone span { color: #85746a; font-size: .76rem; }
.drop-zone.is-dragging { border-color: var(--brand); background: #fff0eb; }
.drop-zone.is-disabled { cursor: not-allowed; opacity: .6; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.selected-files { margin-top: 14px; }
.selected-files__summary { display: flex; gap: 12px; align-items: center; border-bottom: 1px solid #eadfd5; padding: 0 2px 10px; font-size: .78rem; }
.selected-files__summary span { color: #30714d; }
.selected-files__summary span.has-errors { color: #a4362b; }
.selected-files__summary button, .selected-files li > button { margin-left: auto; border: 0; padding: 0; background: transparent; color: #9d3423; cursor: pointer; font-size: .74rem; font-weight: 800; }
.selected-files ul { display: grid; gap: 8px; max-height: 250px; margin: 10px 0 0; padding: 0; overflow: auto; list-style: none; }
.selected-files li { display: flex; gap: 14px; align-items: center; border: 1px solid #e9ddd2; border-radius: 9px; padding: 10px 12px; }
.selected-files li.is-invalid { border-color: #e3b3aa; background: #fff4f1; }
.selected-files li div { display: grid; gap: 3px; min-width: 0; }
.selected-files li strong { overflow: hidden; font-size: .8rem; text-overflow: ellipsis; white-space: nowrap; }
.selected-files li span, .selected-files li small { color: #7b6d63; font-size: .7rem; }
.selected-files li.is-invalid small { color: #a4362b; }
.upload-options { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px; }
.upload-options label:not(.checkbox-option) { display: grid; gap: 6px; color: #695b51; font-size: .74rem; font-weight: 800; }
.upload-options input, .upload-options select { min-width: 0; width: 100%; border: 1px solid #d9ccc1; border-radius: 8px; padding: 9px 10px; background: white; color: #392d26; font: inherit; }
.checkbox-option { display: flex; grid-column: 1 / -1; gap: 8px; align-items: center; color: #695b51; font-size: .76rem; }
.checkbox-option input { width: auto; }
.upload-hint { margin: 12px 0 0; color: #695b51; font-size: .75rem; line-height: 1.6; }
.upload-error { margin: 12px 0 0; border-radius: 8px; padding: 9px 12px; background: #fff0ed; color: #a4362b; font-size: .78rem; }
.upload-actions { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-top: 16px; }
.upload-actions > span { color: #85746a; font-size: .72rem; }
.button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; border-radius: 9px; padding: 8px 14px; cursor: pointer; font-weight: 800; }
.button:disabled { cursor: not-allowed; opacity: .48; }
.button--primary { border: 1px solid var(--brand); background: var(--brand); color: white; }
@media (max-width: 760px) {
  .upload-panel__heading, .upload-actions { align-items: stretch; flex-direction: column; }
  .upload-options { grid-template-columns: 1fr 1fr; }
}
</style>
