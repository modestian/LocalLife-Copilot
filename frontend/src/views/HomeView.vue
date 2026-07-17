<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getReadiness } from '@/api/health'
import ConversationWorkspace from '@/components/ConversationWorkspace.vue'
import StatusCard from '@/components/StatusCard.vue'
import { useAuthStore } from '@/stores/auth'

type ApiState = 'checking' | 'ready' | 'unavailable'

const apiState = ref<ApiState>('checking')
const authStore = useAuthStore()
const router = useRouter()

onMounted(async () => {
  try {
    apiState.value = (await getReadiness()).status === 'ready' ? 'ready' : 'unavailable'
  } catch {
    apiState.value = 'unavailable'
  }
})

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'root' })
}

function login(): void {
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
}
</script>

<template>
  <main class="home-page">
    <div class="topline">
      <span class="eyebrow">LOCAL LIFE · AI COPILOT</span>
      <el-button
        v-if="authStore.isAuthenticated"
        text
        @click="logout"
      >
        退出登录
      </el-button>
      <el-button
        v-else
        type="primary"
        @click="login"
      >
        登录以进行操作
      </el-button>
    </div>
    <h1>一句话，找到此刻想去的地方</h1>
    <p
      v-if="authStore.currentUser"
      class="user-summary"
    >
      {{ authStore.currentUser.display_name }} ·
      {{ authStore.currentUser.roles.map((role) => role.name).join('、') || '普通用户' }}
    </p>
    <p
      v-else
      class="readonly-notice"
    >
      游客只读模式：你可以查看本板块，但不能发起对话、保存会话或提交反馈。
    </p>
    <p class="intro">
      选择场景并补充距离、预算、菜系和人数，继续追问时我们会保留当前会话上下文。
    </p>
    <StatusCard
      label="API 与数据依赖"
      :state="apiState"
    />
    <ConversationWorkspace :read-only="!authStore.isAuthenticated" />
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
