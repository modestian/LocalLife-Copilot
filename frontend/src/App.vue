<script setup lang="ts">
import { onMounted, ref } from 'vue'

import StatusCard from './components/StatusCard.vue'

type ApiState = 'checking' | 'ready' | 'unavailable'

const apiState = ref<ApiState>('checking')
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

onMounted(async () => {
  try {
    const response = await fetch(`${apiBaseUrl}/health/ready`)
    apiState.value = response.ok ? 'ready' : 'unavailable'
  } catch {
    apiState.value = 'unavailable'
  }
})
</script>

<template>
  <main>
    <div class="eyebrow">
      LOCAL LIFE · AI COPILOT
    </div>
    <h1>本地生活智能助手</h1>
    <p class="intro">
      基础服务已经接通。后续功能将在这一套可复现环境上持续交付。
    </p>
    <StatusCard
      label="API 与数据依赖"
      :state="apiState"
    />
    <nav aria-label="开发入口">
      <a :href="`${apiBaseUrl}/docs`">查看 API 文档</a>
      <a :href="`${apiBaseUrl}/health/ready`">查看健康状态</a>
    </nav>
  </main>
</template>
