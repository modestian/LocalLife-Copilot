<script setup lang="ts">
import { computed, ref } from 'vue'

import { useWebSocketChat } from '@/composables/useWebSocketChat'

import SafeMarkdown from './SafeMarkdown.vue'

const props = withDefaults(defineProps<{
  conversationId?: string
  knowledgeBaseIds?: string[]
  readOnly?: boolean
}>(), {
  conversationId: 'conversation-demo-streaming',
  knowledgeBaseIds: () => [],
  readOnly: false,
})

const prompt = ref('推荐两家适合下雨天约会、人均 100 元以内的餐厅')
const chat = useWebSocketChat()
const isActive = computed(() => ['connecting', 'streaming', 'reconnecting'].includes(chat.state.value))
const statusLabel = computed(() => ({
  idle: '等待提问',
  connecting: '正在连接',
  streaming: '正在生成',
  reconnecting: `正在重连 ${chat.reconnectAttempt.value}/3`,
  completed: '回答完成',
  cancelled: '已停止',
  error: '发生错误',
}[chat.state.value]))

async function submit(): Promise<void> {
  if (props.readOnly || !prompt.value.trim() || isActive.value) return
  await chat.send(props.conversationId, prompt.value.trim(), props.knowledgeBaseIds)
}
</script>

<template>
  <section
    class="streaming-panel"
    aria-labelledby="streaming-title"
  >
    <header>
      <div>
        <span>WEBSOCKET · LIVE ANSWER</span>
        <h2 id="streaming-title">
          流式 Markdown 对话
        </h2>
      </div>
      <span
        class="streaming-panel__status"
        :data-state="chat.state.value"
      >
        {{ statusLabel }}
      </span>
    </header>

    <div
      class="streaming-panel__answer"
      aria-live="polite"
    >
      <SafeMarkdown
        v-if="chat.content.value"
        :content="chat.content.value"
      />
      <p
        v-else
        class="streaming-panel__empty"
      >
        回答会按服务端增量顺序稳定渲染；网络中断时使用同一请求自动恢复。
      </p>
      <span
        v-if="chat.state.value === 'streaming'"
        class="streaming-cursor"
        aria-hidden="true"
      />
    </div>

    <p
      v-if="chat.errorMessage.value"
      class="streaming-panel__message"
      :class="{ 'is-error': chat.state.value === 'error' }"
      :role="chat.state.value === 'error' ? 'alert' : 'status'"
    >
      {{ chat.errorMessage.value }}
    </p>

    <div
      v-if="readOnly"
      class="streaming-panel__readonly"
      role="note"
    >
      <strong>当前为只读浏览</strong>
      <span>登录后可发起对话并保存结果。</span>
    </div>
    <form
      v-else
      @submit.prevent="submit"
    >
      <textarea
        v-model="prompt"
        rows="3"
        placeholder="输入需要流式回答的问题"
        @keydown.ctrl.enter="submit"
        @keydown.meta.enter="submit"
      />
      <div class="streaming-panel__actions">
        <button
          v-if="isActive"
          class="is-secondary"
          type="button"
          @click="chat.cancel"
        >
          停止生成
        </button>
        <button
          v-if="chat.state.value === 'error'"
          class="is-secondary"
          type="button"
          @click="chat.retry"
        >
          重试回答
        </button>
        <button
          type="submit"
          :disabled="!prompt.trim() || isActive"
        >
          开始流式回答
        </button>
      </div>
    </form>
    <small v-if="!readOnly">使用短期一次性令牌连接 · 心跳超时自动重连 · Ctrl / ⌘ + Enter 发送</small>
  </section>
</template>

<style scoped>
.streaming-panel { max-width: 760px; margin: 30px 0; padding: 22px; border: 1px solid rgb(74 54 42 / 12%); border-radius: 18px; background: rgb(255 255 255 / 72%); box-shadow: 0 18px 44px rgb(74 54 42 / 7%); }
.streaming-panel header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.streaming-panel header div > span { color: #c34833; font-size: .68rem; font-weight: 800; letter-spacing: .12em; }
.streaming-panel h2 { margin: 4px 0 0; color: #2c211b; font-size: 1.3rem; }
.streaming-panel__status { border-radius: 999px; padding: 5px 9px; background: #eee5dc; color: #695b51; font-size: .7rem; font-weight: 800; }
.streaming-panel__status[data-state="streaming"], .streaming-panel__status[data-state="completed"] { background: #e4f2e9; color: #2c704b; }
.streaming-panel__status[data-state="error"] { background: #fff0ed; color: #a4362b; }
.streaming-panel__answer { position: relative; min-height: 150px; margin: 18px 0 12px; border: 1px solid #eaded3; border-radius: 12px; padding: 16px; background: #fffdfa; }
.streaming-panel__empty { margin: 0; color: #7b6d63; font-size: .88rem; line-height: 1.65; }
.streaming-cursor { display: inline-block; width: 7px; height: 16px; margin-left: 3px; background: #c34833; vertical-align: text-bottom; animation: blink .8s steps(2) infinite; }
.streaming-panel__message { margin: 0 0 10px; border-radius: 8px; padding: 9px 11px; background: #f6eee5; color: #695b51; font-size: .8rem; }
.streaming-panel__message.is-error { background: #fff0ed; color: #a4362b; }
.streaming-panel__readonly { display: flex; gap: 6px; flex-direction: column; border: 1px dashed #d5c6b9; border-radius: 10px; padding: 13px 15px; background: #f8f2eb; color: #695b51; font-size: .84rem; }
.streaming-panel__readonly strong { color: #9d3423; }
.streaming-panel form { display: grid; gap: 9px; }
.streaming-panel textarea { width: 100%; resize: vertical; border: 1px solid #d9ccc1; border-radius: 9px; padding: 10px; background: #fffdfa; color: #392d26; font: inherit; line-height: 1.5; }
.streaming-panel textarea:focus { outline: 2px solid rgb(212 71 45 / 26%); border-color: #c34833; }
.streaming-panel__actions { display: flex; justify-content: flex-end; gap: 8px; }
.streaming-panel button { border: 0; border-radius: 8px; padding: 9px 13px; background: #c34833; color: white; cursor: pointer; font: inherit; font-size: .84rem; font-weight: 800; }
.streaming-panel button.is-secondary { border: 1px solid #d9ccc1; background: #fffdfa; color: #6c5042; }
.streaming-panel button:disabled { cursor: wait; opacity: .55; }
.streaming-panel > small { display: block; margin-top: 10px; color: #88786d; font-size: .68rem; }
@keyframes blink { 50% { opacity: 0; } }
</style>
