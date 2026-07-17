<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { ConversationSummary } from '@/api/conversations'
import { getReadiness } from '@/api/health'
import ConversationWorkspace from '@/components/ConversationWorkspace.vue'
import StatusCard from '@/components/StatusCard.vue'
import { useAuthStore } from '@/stores/auth'

type ApiState = 'checking' | 'ready' | 'unavailable'

const apiState = ref<ApiState>('checking')
const authStore = useAuthStore()
const router = useRouter()

const sampleConversations: ConversationSummary[] = [
  {
    id: 'conversation-demo-gathering',
    title: '周末朋友聚会餐厅',
    scenario: 'gathering',
    status: 'ACTIVE',
    updated_at: '2026-07-17T04:30:00Z',
    message_count: 2,
    preview_messages: [
      {
        id: 'message-demo-user',
        conversation_id: 'conversation-demo-gathering',
        role: 'USER',
        content: '周末六个人聚会，想吃川菜，人均 100 元左右。',
        status: 'COMPLETED',
        created_at: '2026-07-17T04:29:00Z',
      },
      {
        id: 'message-demo-assistant',
        conversation_id: 'conversation-demo-gathering',
        role: 'ASSISTANT',
        content: '收到。我会优先考虑适合多人聊天、可提前订位且近期口碑稳定的川菜馆。你对距离有要求吗？',
        status: 'COMPLETED',
        created_at: '2026-07-17T04:30:00Z',
      },
    ],
  },
]

onMounted(async () => {
  try {
    apiState.value = (await getReadiness()).status === 'ready' ? 'ready' : 'unavailable'
  } catch {
    apiState.value = 'unavailable'
  }
})

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <main class="home-page">
    <div class="topline">
      <span class="eyebrow">LOCAL LIFE · AI COPILOT</span>
      <el-button
        text
        @click="logout"
      >
        退出登录
      </el-button>
    </div>
    <h1>一句话，找到此刻想去的地方</h1>
    <p class="intro">
      选择场景并补充距离、预算、菜系和人数，继续追问时我们会保留当前会话上下文。
    </p>
    <StatusCard
      label="API 与数据依赖"
      :state="apiState"
    />
    <ConversationWorkspace :initial-conversations="sampleConversations" />
    <nav aria-label="开发入口">
      <a
        href="/docs"
        target="_blank"
        rel="noopener noreferrer"
      >查看 API 文档</a>
      <a
        href="/health/ready"
        target="_blank"
        rel="noopener noreferrer"
      >查看健康状态</a>
    </nav>
  </main>
</template>
