<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import {
  conversationApi,
  type ChatMessage,
  type ConversationApi,
  type ConversationScenario,
  type ConversationSummary,
  type ExploreConstraints,
} from '@/api/conversations'
import {
  useWebSocketChat,
  type WebSocketChatController,
  type WebSocketChatState,
} from '@/composables/useWebSocketChat'

import RecommendationResults from './RecommendationResults.vue'
import MessageFeedbackControl from './MessageFeedbackControl.vue'
import SafeMarkdown from './SafeMarkdown.vue'

const props = withDefaults(defineProps<{
  api?: ConversationApi
  initialConversations?: ConversationSummary[]
  stream?: WebSocketChatController
  readOnly?: boolean
  knowledgeBaseIds?: string[]
}>(), {
  api: () => conversationApi,
  initialConversations: () => [],
  stream: undefined,
  readOnly: false,
  knowledgeBaseIds: () => [],
})

interface SceneOption {
  id: ConversationScenario
  icon: string
  title: string
  description: string
  prompt: string
}

const scenes: SceneOption[] = [
  {
    id: 'nearby',
    icon: '⌖',
    title: '附近随便吃',
    description: '结合距离、预算和营业状态快速筛选',
    prompt: '帮我找附近现在营业、口碑不错的店',
  },
  {
    id: 'date',
    icon: '♡',
    title: '约会聚餐',
    description: '偏重氛围、安静程度与体验感',
    prompt: '推荐适合两个人约会、环境安静的餐厅',
  },
  {
    id: 'study',
    icon: '✎',
    title: '学习办公',
    description: '寻找安静、有插座且适合久坐的空间',
    prompt: '找一家适合学习办公、安静且方便久坐的店',
  },
  {
    id: 'gathering',
    icon: '◎',
    title: '朋友聚会',
    description: '按人数、菜系和人均预算规划聚餐',
    prompt: '推荐适合朋友聚会、方便聊天的餐厅',
  },
  {
    id: 'family',
    icon: '⌂',
    title: '家庭用餐',
    description: '关注老人儿童、停车和口味兼容',
    prompt: '推荐适合一家人用餐、老人孩子都方便的店',
  },
]

const standaloneGreetingPattern = /^(?:你好|您好|嗨|哈喽|哈啰|在吗|hello|hi|hey)[!！?？.。,\s，]*$/i
const explorationQueryPattern = /(?:推荐|找|搜|附近|哪里|哪家|吃|餐|饭|菜|火锅|烧烤|面馆|咖啡|甜品|商家|店|馆|人均|预算|公里|营业|约会|聚会|午餐|晚餐|早餐|夜宵|办公|学习)/i

const conversations = ref<ConversationSummary[]>([...props.initialConversations])
const activeConversationId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const defaultStream = useWebSocketChat()
const stream = props.stream ?? defaultStream
const selectedScenario = ref<ConversationScenario>('nearby')
const query = ref('')
const distanceKm = ref<number | null>(3)
const budgetYuan = ref<number | null>(80)
const cuisine = ref('')
const partySize = ref<number | null>(2)
const openNow = ref(true)
const isLoadingConversations = ref(false)
const isLoadingMessages = ref(false)
const isSending = ref(false)
const deletingConversationId = ref<string | null>(null)
const errorMessage = ref('')
const noticeMessage = ref('')
const messageList = ref<HTMLElement | null>(null)
const streamingMessageId = ref<string | null>(null)
const pendingSummaryTitle = ref('')
const explorationContextRequested = ref(false)

const activeConversation = computed(() => (
  conversations.value.find((conversation) => conversation.id === activeConversationId.value) ?? null
))
const selectedScene = computed(() => (
  scenes.find((scene) => scene.id === selectedScenario.value) ?? scenes[0]
))
const canSend = computed(() => !props.readOnly && query.value.trim().length > 0 && !isSending.value)
const streamIsActive = computed(() => (
  ['connecting', 'streaming', 'reconnecting'].includes(stream.state.value)
))

watch(stream.content, async (content) => {
  const message = activeStreamingMessage()
  if (!message) return
  message.content = content
  await scrollToLatest()
})

watch(stream.state, async (state) => {
  const message = activeStreamingMessage()
  if (!message) return

  const statusByState: Partial<Record<WebSocketChatState, ChatMessage['status']>> = {
    connecting: 'STREAMING',
    streaming: 'STREAMING',
    reconnecting: 'STREAMING',
    completed: 'COMPLETED',
    cancelled: 'CANCELLED',
    error: 'FAILED',
  }
  message.status = statusByState[state] ?? message.status
  message.content = stream.content.value
  message.sources = [...stream.sources.value]
  message.recommendations = [...stream.recommendations.value]
  message.fallback = { ...stream.fallback.value }

  if (state === 'completed' && stream.messageId.value) message.id = stream.messageId.value
  if (['completed', 'cancelled', 'error'].includes(state)) {
    updateConversationSummary(message.conversation_id, pendingSummaryTitle.value)
    isSending.value = false
  }
  await scrollToLatest()
})

onMounted(async () => {
  if (!props.readOnly && conversations.value.length === 0) await loadConversations()
})

async function loadConversations(): Promise<void> {
  isLoadingConversations.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    conversations.value = await props.api.listConversations()
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '历史会话加载失败，请稍后重试。')
  } finally {
    isLoadingConversations.value = false
  }
}

function chooseScene(scene: SceneOption): void {
  selectedScenario.value = scene.id
  query.value = scene.prompt
  explorationContextRequested.value = true
}

function startNewConversation(): void {
  if (props.readOnly) return
  resetActiveStream()
  activeConversationId.value = null
  messages.value = []
  query.value = ''
  errorMessage.value = ''
  noticeMessage.value = ''
  explorationContextRequested.value = false
}

async function selectConversation(conversation: ConversationSummary): Promise<void> {
  if (deletingConversationId.value === conversation.id) return
  resetActiveStream()
  activeConversationId.value = conversation.id
  selectedScenario.value = conversation.scenario ?? 'nearby'
  explorationContextRequested.value = false
  errorMessage.value = ''
  noticeMessage.value = ''

  if (conversation.preview_messages) {
    messages.value = [...conversation.preview_messages]
    await scrollToLatest()
    return
  }

  isLoadingMessages.value = true
  try {
    messages.value = await props.api.listMessages(conversation.id)
    await scrollToLatest()
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '会话消息恢复失败，请稍后重试。')
  } finally {
    isLoadingMessages.value = false
  }
}

async function deleteConversation(conversation: ConversationSummary): Promise<void> {
  if (
    props.readOnly
    || deletingConversationId.value
    || !window.confirm(`确认删除探店记录“${conversation.title}”？删除后将无法恢复。`)
  ) return

  deletingConversationId.value = conversation.id
  errorMessage.value = ''
  noticeMessage.value = ''

  const wasActive = activeConversationId.value === conversation.id
  if (wasActive && streamIsActive.value) resetActiveStream()

  try {
    await props.api.deleteConversation(conversation.id)
    conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
    if (activeConversationId.value === conversation.id) {
      activeConversationId.value = null
      messages.value = []
      query.value = ''
      explorationContextRequested.value = false
      resetActiveStream()
    }
    noticeMessage.value = `已删除探店记录“${conversation.title}”。`
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '探店记录删除失败，请稍后重试。')
  } finally {
    deletingConversationId.value = null
  }
}

function currentConstraints(): ExploreConstraints {
  return {
    ...(distanceKm.value ? { distance_km: distanceKm.value } : {}),
    ...(budgetYuan.value ? { budget_yuan: budgetYuan.value } : {}),
    ...(cuisine.value.trim() ? { cuisine: cuisine.value.trim() } : {}),
    ...(partySize.value ? { party_size: partySize.value } : {}),
    open_now: openNow.value,
  }
}

function composeMessage(content: string, constraints: ExploreConstraints): string {
  const details = [
    `场景：${selectedScene.value.title}`,
    constraints.distance_km ? `距离：${constraints.distance_km} 公里内` : '',
    constraints.budget_yuan ? `预算：人均 ${constraints.budget_yuan} 元以内` : '',
    constraints.cuisine ? `菜系/品类：${constraints.cuisine}` : '',
    constraints.party_size ? `人数：${constraints.party_size} 人` : '',
    constraints.open_now ? '营业状态：当前营业' : '',
  ].filter(Boolean)
  return `${content}\n\n[探店条件] ${details.join('；')}`
}

function shouldUseExplorationContext(content: string): boolean {
  if (standaloneGreetingPattern.test(content)) return false
  return explorationContextRequested.value || explorationQueryPattern.test(content)
}

function requestExplorationContext(): void {
  explorationContextRequested.value = true
}

async function sendMessage(): Promise<void> {
  if (props.readOnly || !canSend.value) return

  const content = query.value.trim()
  const useExplorationContext = shouldUseExplorationContext(content)
  const constraints = currentConstraints()
  const composedContent = useExplorationContext
    ? composeMessage(content, constraints)
    : content
  isSending.value = true
  errorMessage.value = ''

  try {
    let conversationId = activeConversationId.value
    if (!conversationId) {
      const conversation = await props.api.createConversation({
        title: content.slice(0, 30),
        scenario: selectedScenario.value,
        ...(useExplorationContext ? { constraints } : {}),
      })
      conversations.value.unshift(conversation)
      activeConversationId.value = conversation.id
      conversationId = conversation.id
    }

    const optimisticMessageId = `local-${crypto.randomUUID()}`
    messages.value.push({
      id: optimisticMessageId,
      conversation_id: conversationId,
      role: 'USER',
      content,
      status: 'COMPLETED',
      created_at: new Date().toISOString(),
    })
    streamingMessageId.value = `stream-${crypto.randomUUID()}`
    pendingSummaryTitle.value = content
    messages.value.push({
      id: streamingMessageId.value,
      conversation_id: conversationId,
      role: 'ASSISTANT',
      content: '',
      status: 'STREAMING',
      created_at: new Date().toISOString(),
      sources: [],
      recommendations: [],
      fallback: { triggered: false },
    })
    query.value = ''
    await scrollToLatest()

    await stream.send(conversationId, composedContent, props.knowledgeBaseIds)
    if (useExplorationContext) explorationContextRequested.value = false
  } catch (error: unknown) {
    query.value = content
    if (streamingMessageId.value) {
      messages.value = messages.value.filter((message) => message.id !== streamingMessageId.value)
      streamingMessageId.value = null
    }
    errorMessage.value = getErrorMessage(error, '消息发送失败，请检查网络后重试。')
    isSending.value = false
  }
}

function activeStreamingMessage(): ChatMessage | undefined {
  return messages.value.find((message) => message.id === streamingMessageId.value)
}

async function retryStreamingMessage(): Promise<void> {
  const message = activeStreamingMessage()
  if (!message) return
  message.status = 'STREAMING'
  isSending.value = true
  await stream.retry()
}

function cancelStreamingMessage(): void {
  stream.cancel()
}

function resetActiveStream(): void {
  if (streamIsActive.value) stream.cancel()
  streamingMessageId.value = null
  pendingSummaryTitle.value = ''
  isSending.value = false
}

function applyRefinement(suggestion: string): void {
  query.value = suggestion
}

function streamStatusLabel(status: ChatMessage['status']): string {
  if (status === 'STREAMING') {
    return stream.state.value === 'reconnecting'
      ? `正在重连 ${stream.reconnectAttempt.value}/3`
      : '正在生成'
  }
  return ({ COMPLETED: '回答完成', FAILED: '生成失败', CANCELLED: '已停止' })[status] ?? ''
}

function updateConversationSummary(conversationId: string, fallbackTitle: string): void {
  const conversation = conversations.value.find((item) => item.id === conversationId)
  if (!conversation) return
  conversation.title ||= fallbackTitle.slice(0, 30)
  conversation.updated_at = new Date().toISOString()
  conversation.message_count = messages.value.length
}

async function scrollToLatest(): Promise<void> {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <section
    class="conversation-workspace"
    aria-label="用户探店工作台"
  >
    <aside class="conversation-sidebar">
      <div class="conversation-sidebar__heading">
        <div>
          <span>CONVERSATIONS</span>
          <h2>探店记录</h2>
        </div>
        <button
          v-if="!readOnly"
          type="button"
          @click="startNewConversation"
        >
          ＋ 新对话
        </button>
      </div>

      <p
        v-if="readOnly"
        class="conversation-sidebar__state"
      >
        游客可以浏览探店场景，登录后可查看和保存历史会话。
      </p>
      <p
        v-else-if="isLoadingConversations"
        class="conversation-sidebar__state"
        role="status"
      >
        正在加载历史会话…
      </p>
      <p
        v-else-if="conversations.length === 0"
        class="conversation-sidebar__state"
      >
        还没有历史会话，从右侧选择一个场景开始吧。
      </p>
      <ul
        v-else
        class="conversation-list"
      >
        <li
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-list__item"
        >
          <button
            class="conversation-list__select"
            :class="{ 'is-active': activeConversationId === conversation.id }"
            :data-conversation-id="conversation.id"
            :disabled="deletingConversationId === conversation.id"
            type="button"
            @click="selectConversation(conversation)"
          >
            <strong>{{ conversation.title }}</strong>
            <span>
              {{ conversation.message_count ?? 0 }} 条消息 · {{ formatTime(conversation.updated_at) }}
            </span>
          </button>
          <button
            v-if="!readOnly"
            class="conversation-list__delete"
            :aria-label="`删除探店记录“${conversation.title}”`"
            :data-delete-conversation-id="conversation.id"
            :disabled="deletingConversationId !== null"
            type="button"
            @click="deleteConversation(conversation)"
          >
            {{ deletingConversationId === conversation.id ? '删除中' : '删除' }}
          </button>
        </li>
      </ul>
    </aside>

    <div class="conversation-main">
      <header class="conversation-main__heading">
        <div>
          <span>{{ activeConversation ? 'CONTINUE EXPLORING' : 'START EXPLORING' }}</span>
          <h2>{{ activeConversation?.title ?? '今天想去哪儿？' }}</h2>
        </div>
        <span class="conversation-main__status">上下文已保留</span>
      </header>

      <div
        v-if="messages.length === 0 && !isLoadingMessages"
        class="scene-entry"
      >
        <p>选择一个场景，我们会把距离、预算、菜系和人数一起带入对话。</p>
        <div class="scene-grid">
          <button
            v-for="scene in scenes"
            :key="scene.id"
            :class="{ 'is-active': selectedScenario === scene.id }"
            :data-scenario="scene.id"
            type="button"
            @click="chooseScene(scene)"
          >
            <span aria-hidden="true">{{ scene.icon }}</span>
            <strong>{{ scene.title }}</strong>
            <small>{{ scene.description }}</small>
          </button>
        </div>
      </div>

      <div
        v-else
        ref="messageList"
        class="message-list"
        aria-live="polite"
      >
        <p
          v-if="isLoadingMessages"
          class="message-list__state"
          role="status"
        >
          正在恢复会话消息…
        </p>
        <article
          v-for="message in messages"
          :key="message.id"
          class="chat-message"
          :class="message.role === 'USER' ? 'is-user' : 'is-assistant'"
        >
          <div class="chat-message__meta">
            <strong>{{ message.role === 'USER' ? '你' : '探店助手' }}</strong>
            <span>{{ formatTime(message.created_at) }}</span>
          </div>
          <SafeMarkdown
            v-if="message.role === 'ASSISTANT' && message.content"
            :content="message.content"
          />
          <p v-else-if="message.content">
            {{ message.content }}
          </p>
          <div
            v-else-if="message.status === 'STREAMING'"
            class="assistant-thinking"
            role="status"
          >
            <span /><span /><span /> 正在结合当前条件查找合适的商家…
          </div>
          <div
            v-if="message.role === 'ASSISTANT'"
            class="streaming-message-state"
            :data-state="message.status.toLowerCase()"
          >
            <span>{{ streamStatusLabel(message.status) }}</span>
            <button
              v-if="message.id === streamingMessageId && streamIsActive"
              type="button"
              @click="cancelStreamingMessage"
            >
              停止生成
            </button>
            <button
              v-if="message.id === streamingMessageId && message.status === 'FAILED'"
              type="button"
              @click="retryStreamingMessage"
            >
              重试回答
            </button>
          </div>
          <p
            v-if="message.id === streamingMessageId && stream.errorMessage.value"
            class="streaming-message-error"
            :role="message.status === 'FAILED' ? 'alert' : 'status'"
          >
            {{ stream.errorMessage.value }}
          </p>
          <RecommendationResults
            v-if="message.role === 'ASSISTANT' && (message.recommendations?.length || message.sources?.length || message.fallback?.triggered)"
            :recommendations="message.recommendations ?? []"
            :sources="message.sources ?? []"
            :fallback="message.fallback"
            @refine="applyRefinement"
          />
          <MessageFeedbackControl
            v-if="!readOnly && message.role === 'ASSISTANT' && message.status === 'COMPLETED'"
            :conversation-id="message.conversation_id"
            :message-id="message.id"
          />
        </article>
      </div>

      <p
        v-if="errorMessage"
        class="conversation-error"
        role="alert"
      >
        {{ errorMessage }}
      </p>
      <p
        v-if="noticeMessage"
        class="conversation-notice"
        role="status"
      >
        {{ noticeMessage }}
      </p>

      <div
        v-if="readOnly"
        class="conversation-readonly"
        role="note"
      >
        <strong>当前为只读浏览</strong>
        <span>登录后可填写探店条件、发起对话并保存结果。</span>
      </div>
      <form
        v-else
        class="composer"
        @submit.prevent="sendMessage"
      >
        <div class="condition-grid">
          <label>
            <span>距离</span>
            <select
              v-model.number="distanceKm"
              @change="requestExplorationContext"
            >
              <option :value="1">1 公里内</option>
              <option :value="3">3 公里内</option>
              <option :value="5">5 公里内</option>
              <option :value="10">10 公里内</option>
            </select>
          </label>
          <label>
            <span>人均预算</span>
            <input
              v-model.number="budgetYuan"
              min="1"
              type="number"
              placeholder="元/人"
              @change="requestExplorationContext"
            >
          </label>
          <label>
            <span>菜系 / 品类</span>
            <input
              v-model="cuisine"
              type="text"
              placeholder="川菜、咖啡…"
              @change="requestExplorationContext"
            >
          </label>
          <label>
            <span>人数</span>
            <input
              v-model.number="partySize"
              min="1"
              type="number"
              @change="requestExplorationContext"
            >
          </label>
          <label class="open-now-option">
            <input
              v-model="openNow"
              type="checkbox"
              @change="requestExplorationContext"
            >
            <span>仅看当前营业</span>
          </label>
        </div>
        <div class="composer__input">
          <textarea
            v-model="query"
            :placeholder="activeConversation ? '继续补充条件或追问…' : '描述你想找的店，例如：适合写作业的安静咖啡馆'"
            rows="3"
            @keydown.ctrl.enter="sendMessage"
            @keydown.meta.enter="sendMessage"
          />
          <button
            :disabled="!canSend"
            type="submit"
          >
            {{ isSending ? '发送中…' : '发送' }}
          </button>
        </div>
        <small>Ctrl / ⌘ + Enter 发送 · AI 推荐仅供参考，请以商家最新信息为准</small>
      </form>
    </div>
  </section>
</template>

<style scoped>
.conversation-workspace { display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: 720px; overflow: hidden; border: 1px solid var(--line); border-radius: 22px; background: rgb(255 254 252 / 82%); box-shadow: var(--shadow); backdrop-filter: blur(14px); }
.conversation-sidebar { overflow: hidden; padding: 20px; border-right: 1px solid #e7dbd0; background: linear-gradient(160deg, #fbf4ed, #f4ebe2); }
.conversation-sidebar__heading, .conversation-main__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.conversation-sidebar__heading span, .conversation-main__heading > div > span { color: #c34833; font-size: .67rem; font-weight: 800; letter-spacing: .12em; }
.conversation-sidebar h2, .conversation-main h2 { margin: 4px 0 0; color: #2c211b; font-size: 1.25rem; }
.conversation-sidebar__heading button { border: 0; border-radius: 8px; padding: 7px 9px; background: var(--brand); color: white; cursor: pointer; font: inherit; font-size: .75rem; font-weight: 700; box-shadow: 0 6px 14px rgb(176 60 39 / 18%); transition: transform .2s var(--ease-out), background .2s ease; }
.conversation-sidebar__heading button:hover { background: var(--brand-strong); transform: translateY(-1px); }
.conversation-sidebar__state { margin: 24px 0; color: #7b6d63; font-size: .82rem; line-height: 1.6; }
.conversation-list { display: grid; max-height: min(560px, calc(100dvh - 230px)); gap: 7px; margin: 20px -6px 0 0; overflow-y: auto; padding: 0 6px 0 0; list-style: none; overscroll-behavior: contain; scrollbar-color: #d4b7aa transparent; scrollbar-width: thin; }
.conversation-list::-webkit-scrollbar { width: 5px; }
.conversation-list::-webkit-scrollbar-thumb { border-radius: 999px; background: #d4b7aa; }
.conversation-list::-webkit-scrollbar-track { background: transparent; }
.conversation-list__item { position: relative; }
.conversation-list__select { display: grid; gap: 5px; width: 100%; border: 1px solid transparent; border-radius: 10px; padding: 11px 52px 11px 11px; background: transparent; color: #493a31; cursor: pointer; text-align: left; transition: background .2s ease, border-color .2s ease, transform .2s var(--ease-out); }
.conversation-list__select:hover, .conversation-list__select.is-active { border-color: #dec9bb; background: #fffaf5; }
.conversation-list__select:hover { transform: translateX(2px); }
.conversation-list__select:disabled { cursor: wait; opacity: .6; }
.conversation-list__delete { position: absolute; top: 50%; right: 7px; border: 0; border-radius: 7px; padding: 5px 7px; background: transparent; color: #a44334; cursor: pointer; font: inherit; font-size: .68rem; font-weight: 700; transform: translateY(-50%); transition: background .2s ease, color .2s ease; }
.conversation-list__delete:hover { background: #f9e2dc; color: #8c2f22; }
.conversation-list__delete:disabled { cursor: wait; opacity: .55; }
.conversation-list strong { overflow: hidden; font-size: .86rem; text-overflow: ellipsis; white-space: nowrap; }
.conversation-list span { color: #88786d; font-size: .68rem; }
.conversation-main { display: flex; min-width: 0; flex-direction: column; padding: 24px; }
.conversation-main__heading { padding-bottom: 16px; border-bottom: 1px solid #eaded3; }
.conversation-main__status { border-radius: 999px; padding: 5px 9px; background: #e9f4ed; color: #2f7650; font-size: .7rem; font-weight: 700; }
.scene-entry { flex: 1; padding: 34px 0 24px; }
.scene-entry > p { margin: 0 0 18px; color: #695b51; font-size: .9rem; }
.scene-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.scene-grid button { display: grid; grid-template-columns: 30px 1fr; gap: 3px 8px; align-items: center; border: 1px solid #e5d7cc; border-radius: 12px; padding: 14px; background: #fffdfa; color: #493a31; cursor: pointer; text-align: left; transition: transform .22s var(--ease-out), box-shadow .22s ease, border-color .22s ease, background .22s ease; }
.scene-grid button:hover, .scene-grid button.is-active { border-color: #d26b57; background: #fff5f1; }
.scene-grid button:hover { box-shadow: 0 8px 18px rgb(112 73 48 / 9%); transform: translateY(-2px); }
.scene-grid button > span { grid-row: span 2; color: #c34833; font-size: 1.4rem; text-align: center; }
.scene-grid strong { font-size: .88rem; }
.scene-grid small { color: #7b6d63; font-size: .72rem; line-height: 1.4; }
.message-list { display: grid; flex: 1; gap: 14px; max-height: 440px; overflow-y: auto; padding: 22px 2px; }
.message-list__state { color: #7b6d63; font-size: .86rem; }
.chat-message { max-width: 82%; border-radius: 14px; padding: 12px 14px; animation: message-in 280ms var(--ease-out) both; }
.chat-message.is-user { justify-self: end; background: linear-gradient(135deg, #c94b32, #b43b29); box-shadow: 0 8px 18px rgb(176 60 39 / 17%); color: white; }
.chat-message.is-assistant { justify-self: start; border: 1px solid #eaded3; background: #fffdfa; color: #41342c; }
.chat-message__meta { display: flex; justify-content: space-between; gap: 18px; font-size: .68rem; opacity: .74; }
.chat-message p { margin: 7px 0 0; line-height: 1.65; white-space: pre-wrap; }
.chat-message :deep(.safe-markdown) { margin-top: 8px; }
.chat-message :deep(.safe-markdown > :first-child) { margin-top: 0; }
.chat-message :deep(.safe-markdown > :last-child) { margin-bottom: 0; }
.assistant-thinking { color: #7b6d63; font-size: .8rem; }
.assistant-thinking span { display: inline-block; width: 5px; height: 5px; margin-right: 3px; border-radius: 50%; background: #c34833; }
.conversation-error { margin: 0 0 10px; border-radius: 8px; padding: 9px 11px; background: #fff0ed; color: #a4362b; font-size: .8rem; }
.conversation-notice { margin: 0 0 10px; border-radius: 8px; padding: 9px 11px; background: #e9f4ed; color: #2f7650; font-size: .8rem; }
.conversation-readonly { display: flex; gap: 6px; flex-direction: column; margin-top: 14px; border: 1px dashed #d5c6b9; border-radius: 10px; padding: 13px 15px; background: #f8f2eb; color: #695b51; font-size: .84rem; }
.conversation-readonly strong { color: #9d3423; }
.streaming-message-state { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; color: #75675d; font-size: .7rem; font-weight: 700; }
.streaming-message-state button { border: 1px solid #d9ccc1; border-radius: 7px; padding: 5px 8px; background: #fffdfa; color: #8e3a2b; cursor: pointer; font: inherit; }
.streaming-message-state[data-state="failed"] { color: #a4362b; }
.streaming-message-error { border-radius: 7px; padding: 7px 9px; background: #fff0ed; color: #a4362b; font-size: .75rem; }
.chat-message :deep(.recommendation-results) { width: min(780px, calc(100vw - 390px)); margin: 16px 0 0; box-shadow: none; }
.composer { display: grid; gap: 10px; padding-top: 14px; border-top: 1px solid #eaded3; }
.condition-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)) auto; gap: 8px; align-items: end; }
.condition-grid label { display: grid; gap: 4px; color: #75675d; font-size: .7rem; font-weight: 700; }
.condition-grid input, .condition-grid select, .composer textarea { min-width: 0; border: 1px solid #d9ccc1; border-radius: 8px; padding: 8px; background: #fffdfa; color: #392d26; font: inherit; }
.condition-grid input:focus, .condition-grid select:focus, .composer textarea:focus { outline: 2px solid rgb(212 71 45 / 26%); border-color: #c34833; }
.open-now-option { display: flex !important; flex-direction: row; align-items: center; padding-bottom: 8px; white-space: nowrap; }
.composer__input { display: flex; gap: 8px; align-items: flex-end; }
.composer textarea { width: 100%; resize: vertical; line-height: 1.5; }
.composer__input button { min-width: 76px; border: 0; border-radius: 9px; padding: 11px 16px; background: var(--brand); color: white; cursor: pointer; font: inherit; font-weight: 800; box-shadow: 0 7px 16px rgb(176 60 39 / 17%); transition: transform .2s var(--ease-out), background .2s ease, box-shadow .2s ease; }
.composer__input button:not(:disabled):hover { background: var(--brand-strong); box-shadow: 0 10px 20px rgb(176 60 39 / 24%); transform: translateY(-1px); }
.composer__input button:disabled { cursor: wait; opacity: .55; }
.composer > small { color: #88786d; font-size: .68rem; }
@keyframes message-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 900px) { .conversation-workspace { grid-template-columns: 220px minmax(0, 1fr); } .condition-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { .conversation-workspace { display: block; min-height: auto; } .conversation-sidebar { border-right: 0; border-bottom: 1px solid #e7dbd0; overflow: visible; } .conversation-list { display: flex; max-height: none; overflow-x: auto; overflow-y: hidden; } .conversation-list li { min-width: 190px; } .conversation-main { padding: 18px; } .scene-grid { grid-template-columns: 1fr; } .chat-message { max-width: 92%; } .chat-message :deep(.recommendation-results) { width: 100%; } }
@media (max-width: 430px) { .condition-grid { grid-template-columns: 1fr 1fr; } .open-now-option { grid-column: span 2; } .composer__input { align-items: stretch; flex-direction: column; } .composer__input button { width: 100%; } }
</style>
