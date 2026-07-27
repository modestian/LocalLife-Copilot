<script setup lang="ts">
import { computed, ref } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { feedbackApi } from '@/api/feedback'
import type { ChatFeedbackPayload, FeedbackApi, FeedbackRating } from '@/types/feedback'

const props = withDefaults(defineProps<{
  conversationId: string
  messageId: string
  api?: FeedbackApi
  disabled?: boolean
}>(), {
  api: () => feedbackApi,
  disabled: false,
})

const reasonOptions = [
  { code: 'FACT_ERROR', label: '事实有误' },
  { code: 'OUTDATED', label: '信息过期' },
] as const

const negativeFormOpen = ref(false)
const selectedReasons = ref<string[]>([])
const correction = ref('')
const submittedRating = ref<FeedbackRating | null>(null)
const submitting = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const correctionLength = computed(() => correction.value.length)
const hasNegativeDetail = computed(
  () => selectedReasons.value.length > 0 || correction.value.trim().length > 0,
)

function resetSubmissionState(): void {
  errorMessage.value = ''
  successMessage.value = ''
}

function openNegativeForm(): void {
  if (props.disabled || submitting.value) return
  resetSubmissionState()
  negativeFormOpen.value = true
}

function editFeedback(): void {
  if (props.disabled || submitting.value) return
  resetSubmissionState()
  negativeFormOpen.value = submittedRating.value === -1
}

function buildPayload(rating: FeedbackRating): ChatFeedbackPayload {
  const normalizedCorrection = correction.value.trim()
  const payload: ChatFeedbackPayload = {
    conversation_id: props.conversationId,
    message_id: props.messageId,
    rating,
  }

  if (rating === -1 && selectedReasons.value.length) {
    payload.reason_codes = [...selectedReasons.value]
  }
  if (rating === -1 && normalizedCorrection) {
    payload.correction = normalizedCorrection
  }
  return payload
}

async function submit(rating: FeedbackRating): Promise<void> {
  if (props.disabled || submitting.value) return
  if (rating === -1 && !hasNegativeDetail.value) {
    errorMessage.value = '请至少选择一个问题原因，或填写修正答案。'
    successMessage.value = ''
    return
  }

  submitting.value = true
  resetSubmissionState()
  try {
    await props.api.submit(buildPayload(rating))
    submittedRating.value = rating
    negativeFormOpen.value = false
    successMessage.value = rating === 1 ? '已记录“有帮助”反馈。' : '反馈已提交，感谢你的修正。'
  } catch (error) {
    errorMessage.value = getUserFacingError(error, '反馈提交失败，请稍后重试。')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section
    class="message-feedback"
    aria-label="回答反馈"
  >
    <div class="message-feedback__bar">
      <span>这条回答对你有帮助吗？</span>
      <div class="message-feedback__actions">
        <button
          type="button"
          :aria-pressed="submittedRating === 1"
          :disabled="disabled || submitting"
          @click="submit(1)"
        >
          {{ submitting && !negativeFormOpen ? '提交中…' : '有帮助' }}
        </button>
        <button
          class="message-feedback__negative"
          type="button"
          :aria-expanded="negativeFormOpen"
          :aria-pressed="submittedRating === -1"
          :disabled="disabled || submitting"
          @click="openNegativeForm"
        >
          需要改进
        </button>
        <button
          v-if="submittedRating !== null"
          class="message-feedback__edit"
          type="button"
          :disabled="disabled || submitting"
          @click="editFeedback"
        >
          修改反馈
        </button>
      </div>
    </div>

    <form
      v-if="negativeFormOpen"
      class="message-feedback__form"
      @submit.prevent="submit(-1)"
    >
      <fieldset>
        <legend>问题原因（可多选）</legend>
        <label
          v-for="option in reasonOptions"
          :key="option.code"
        >
          <input
            v-model="selectedReasons"
            type="checkbox"
            :value="option.code"
            :disabled="disabled || submitting"
          >
          {{ option.label }}
        </label>
      </fieldset>
      <label class="message-feedback__correction">
        <span>修正答案（可选，最多 4000 字）</span>
        <textarea
          v-model="correction"
          maxlength="4000"
          :disabled="disabled || submitting"
          placeholder="请补充正确的信息或更合适的回答…"
        />
        <small>{{ correctionLength }} / 4000</small>
      </label>
      <p class="message-feedback__hint">
        提交差评时，请至少选择一个原因或填写修正答案。
      </p>
      <div class="message-feedback__form-actions">
        <button
          type="submit"
          :disabled="disabled || submitting"
        >
          {{ submitting ? '提交中…' : '提交反馈' }}
        </button>
        <button
          type="button"
          :disabled="submitting"
          @click="negativeFormOpen = false"
        >
          取消
        </button>
      </div>
    </form>

    <p
      v-if="successMessage"
      class="message-feedback__success"
      role="status"
    >
      {{ successMessage }}
    </p>
    <p
      v-if="errorMessage"
      class="message-feedback__error"
      role="alert"
    >
      {{ errorMessage }}
    </p>
  </section>
</template>

<style scoped>
.message-feedback {
  display: grid;
  gap: 8px;
  margin-top: 12px;
  color: var(--text-secondary, #5f6b7a);
  font-size: 13px;
}

.message-feedback__bar,
.message-feedback__actions,
.message-feedback__form-actions,
.message-feedback fieldset {
  display: flex;
  align-items: center;
  gap: 8px;
}

.message-feedback__bar {
  flex-wrap: wrap;
}

.message-feedback__actions {
  flex-wrap: wrap;
}

.message-feedback button {
  min-height: 30px;
  padding: 4px 10px;
  border: 1px solid #d6dde8;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  cursor: pointer;
}

.message-feedback button:hover:not(:disabled),
.message-feedback button[aria-pressed="true"] {
  border-color: #3b82f6;
  background: #eff6ff;
  color: #1d4ed8;
}

.message-feedback__negative:hover:not(:disabled),
.message-feedback__negative[aria-pressed="true"] {
  border-color: #f97316;
  background: #fff7ed;
  color: #c2410c;
}

.message-feedback button:disabled {
  cursor: not-allowed;
  opacity: .6;
}

.message-feedback__edit {
  border-style: dashed !important;
}

.message-feedback__form {
  display: grid;
  gap: 10px;
  max-width: 560px;
  padding: 12px;
  border: 1px solid #dbe5f0;
  border-radius: 8px;
  background: #f8fafc;
}

.message-feedback fieldset {
  flex-wrap: wrap;
  margin: 0;
  padding: 0;
  border: 0;
}

.message-feedback legend {
  width: 100%;
  margin-bottom: 6px;
  color: #334155;
  font-weight: 600;
}

.message-feedback fieldset label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.message-feedback__correction {
  display: grid;
  gap: 5px;
  color: #334155;
  font-weight: 600;
}

.message-feedback textarea {
  min-height: 84px;
  padding: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  resize: vertical;
  font: inherit;
}

.message-feedback__correction small {
  justify-self: end;
  color: #64748b;
  font-weight: 400;
}

.message-feedback__hint,
.message-feedback__success,
.message-feedback__error {
  margin: 0;
}

.message-feedback__hint {
  color: #64748b;
}

.message-feedback__success {
  color: #15803d;
}

.message-feedback__error {
  color: #b91c1c;
}

@media (max-width: 560px) {
  .message-feedback__bar,
  .message-feedback__actions,
  .message-feedback__form-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
