<script setup lang="ts">
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

defineProps<{
  title: string
  description: string
  entry?: { to: string; label: string; description: string }
}>()

const authStore = useAuthStore()
const router = useRouter()

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
    <h1>{{ title }}</h1>
    <p
      v-if="authStore.currentUser"
      class="user-summary"
    >
      {{ authStore.currentUser.display_name }} ·
      {{ authStore.currentUser.roles.map((role) => role.name).join('、') }}
    </p>
    <p
      v-else
      class="readonly-notice"
    >
      游客只读模式：本板块内容可直接查看，新建、编辑、删除和提交操作均不可用。
    </p>
    <p class="intro">
      {{ description }}
    </p>
    <router-link
      v-if="entry"
      class="workspace-entry"
      :to="entry.to"
    >
      <span>{{ entry.label }} →</span>
      <small>{{ entry.description }}</small>
    </router-link>
  </main>
</template>
