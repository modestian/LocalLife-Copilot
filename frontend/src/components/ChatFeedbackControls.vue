<script setup lang="ts">
import { computed, ref } from 'vue'

import {
  submitChatFeedback,
  type ChatFeedbackPayload,
  type FeedbackRating,
} from '@/api/feedback'

type SubmissionState = 'idle' | 'submitting' | 'success' | 'error'

const feedbackReasons = [
  { value: 'FACT_ERROR', label: '事实有误' },
  { value: 'OUTDATED', label: '信息过期' },
  { value: 'IRRELEVANT', label: '没有解决问题' },
  { value: 'UNSAFE', label: '内容不妥' },
]

const props = defineProps<{
  conversationId: string
  messageId: string
  submitFeedback?: (payload: ChatFeedbackPayload) => Promise<void>
}>()

const selectedRating = ref<FeedbackRating | null>(null)
const reasonCodes = ref<string[]>([])
const correction = ref('')
const state = ref<SubmissionState>('idle')
const errorMessage = ref('')
const validationMessage = ref('')
const lastPayload = ref<ChatFeedbackPayload | null>(null)

const isSubmitting = computed(() => state.value === 'submitting')
const showNegativeForm = computed(() => selectedRating.value === -1 && state.value !== 'success')

function clearMessages(): void {
  state.value = 'idle'
  errorMessage.value = ''
  validationMessage.value = ''
}

function buildPayload(rating: FeedbackRating): ChatFeedbackPayload {
  const trimmedCorrection = correction.value.trim()
  return {
    conversation_id: props.conversationId,
    message_id: props.messageId,
    rating,
    reason_codes: rating === -1 ? reasonCodes.value : [],
    ...(trimmedCorrection ? { correction: trimmedCorrection } : {}),
  }
}

async function submit(payload: ChatFeedbackPayload): Promise<void> {
  state.value = 'submitting'
  errorMessage.value = ''
  lastPayload.value = payload

  try {
    await (props.submitFeedback ?? submitChatFeedback)(payload)
    state.value = 'success'
  } catch (error: unknown) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '网络连接异常，请稍后重试。'
  }
}

async function selectRating(rating: FeedbackRating): Promise<void> {
  if (isSubmitting.value) return

  selectedRating.value = rating
  clearMessages()
  if (rating === 1) {
    await submit(buildPayload(rating))
  }
}

async function submitNegativeFeedback(): Promise<void> {
  const hasCorrection = correction.value.trim().length > 0
  if (reasonCodes.value.length === 0 && !hasCorrection) {
    validationMessage.value = '请选择原因，或填写修正答案后再提交。'
    return
  }

  validationMessage.value = ''
  await submit(buildPayload(-1))
}

async function retry(): Promise<void> {
  if (lastPayload.value) await submit(lastPayload.value)
}

function editFeedback(): void {
  clearMessages()
  if (selectedRating.value === 1) selectedRating.value = null
}
</script>

<template>
  <section
    class="feedback-controls"
    aria-label="回答反馈"
  >
    <div class="feedback-controls__prompt">
      <span>这条回答对你有帮助吗？</span>
      <div class="feedback-controls__actions">
        <button
          class="feedback-button"
          :class="{ 'is-selected': selectedRating === 1 }"
          type="button"
          :aria-pressed="selectedRating === 1"
          :disabled="isSubmitting"
          @click="selectRating(1)"
        >
          <span aria-hidden="true">👍</span> 有帮助
        </button>
        <button
          class="feedback-button"
          :class="{ 'is-selected': selectedRating === -1 }"
          type="button"
          :aria-pressed="selectedRating === -1"
          :disabled="isSubmitting"
          @click="selectRating(-1)"
        >
          <span aria-hidden="true">👎</span> 不准确
        </button>
      </div>
    </div>

    <form
      v-if="showNegativeForm"
      class="feedback-form"
      @submit.prevent="submitNegativeFeedback"
    >
      <fieldset :disabled="isSubmitting">
        <legend>告诉我们哪里需要改进</legend>
        <div class="feedback-reasons">
          <label
            v-for="reason in feedbackReasons"
            :key="reason.value"
          >
            <input
              v-model="reasonCodes"
              type="checkbox"
              :value="reason.value"
            >
            {{ reason.label }}
          </label>
        </div>
        <label class="feedback-correction">
          <span>修正答案（可选）</span>
          <textarea
            v-model="correction"
            maxlength="4000"
            placeholder="例如：该店周一闭店，且人均约 80 元。"
            rows="3"
          />
          <small>{{ correction.length }}/4000</small>
        </label>
      </fieldset>
      <p
        v-if="validationMessage"
        class="feedback-message is-error"
        role="alert"
      >
        {{ validationMessage }}
      </p>
      <button
        class="feedback-submit"
        type="submit"
        :disabled="isSubmitting"
      >
        {{ isSubmitting ? '提交中…' : '提交反馈' }}
      </button>
    </form>

    <p
      v-if="state === 'success'"
      class="feedback-message is-success"
      role="status"
    >
      感谢你的反馈，已成功记录。再次提交将更新本条反馈。
      <button
        type="button"
        @click="editFeedback"
      >
        编辑
      </button>
    </p>
    <p
      v-else-if="state === 'error'"
      class="feedback-message is-error"
      role="alert"
    >
      提交失败：{{ errorMessage }}
      <button
        type="button"
        :disabled="isSubmitting"
        @click="retry"
      >
        重试
      </button>
    </p>
  </section>
</template>

<style scoped>
.feedback-controls { margin-top: 18px; padding-top: 16px; border-top: 1px solid rgb(74 54 42 / 12%); color: #56483e; }
.feedback-controls__prompt { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; font-size: .9rem; }
.feedback-controls__actions, .feedback-reasons { display: flex; flex-wrap: wrap; gap: 8px; }
.feedback-button, .feedback-submit, .feedback-message button { border: 1px solid #d9ccc1; border-radius: 999px; background: #fffaf5; color: #59483d; cursor: pointer; font: inherit; }
.feedback-button { padding: 7px 10px; font-size: .85rem; }
.feedback-button:hover, .feedback-button.is-selected { border-color: #c34833; background: #fff0eb; color: #a52f20; }
.feedback-button:disabled, .feedback-submit:disabled { cursor: wait; opacity: .6; }
.feedback-form { margin-top: 14px; padding: 14px; border-radius: 12px; background: #fbf5ee; }
fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
legend { margin-bottom: 10px; font-size: .88rem; font-weight: 700; }
.feedback-reasons label { display: inline-flex; align-items: center; gap: 5px; font-size: .85rem; }
.feedback-correction { display: grid; gap: 6px; margin-top: 14px; font-size: .85rem; font-weight: 700; }
textarea { width: 100%; resize: vertical; border: 1px solid #d9ccc1; border-radius: 8px; padding: 8px; background: #fffdfa; color: #392d26; font: inherit; font-size: .9rem; }
textarea:focus { outline: 2px solid rgb(212 71 45 / 30%); border-color: #c34833; }
small { color: #7b6d63; font-weight: 400; text-align: right; }
.feedback-submit { margin-top: 12px; padding: 8px 14px; border: 0; background: #c34833; color: white; font-weight: 700; }
.feedback-message { margin: 12px 0 0; font-size: .86rem; line-height: 1.6; }
.feedback-message button { margin-left: 6px; padding: 2px 7px; text-decoration: underline; }
.is-success { color: #247044; }
.is-error { color: #a4362b; }
</style>
