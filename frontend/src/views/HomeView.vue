<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getReadiness } from '@/api/health'
import type { SearchResult } from '@/api/search'
import SearchDebugPanel from '@/components/SearchDebugPanel.vue'
import StatusCard from '@/components/StatusCard.vue'
import { useAuthStore } from '@/stores/auth'

type ApiState = 'checking' | 'ready' | 'unavailable'

const apiState = ref<ApiState>('checking')
const authStore = useAuthStore()
const router = useRouter()

const sampleResults: SearchResult[] = [
  {
    chunk_id: 'chunk-demo-001',
    document_id: 'review-demo-001',
    merchant_id: 'merchant-demo-001',
    content: '环境安静，靠窗位置适合四人讨论，工作日下午客流较少。',
    source_location: '点评 / 星光咖啡 / 2026-07-12',
    source_url: '/app/reviews/review-demo-001',
    score: 0.824,
    score_detail: { bm25: 0.612, vector: 0.887, fusion: 0.846 },
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
    <h1>用户工作台已就绪</h1>
    <p class="intro">
      Vue、路由、状态管理、组件库与类型化 API Client 已接通，可继续实现探店和流式对话。
    </p>
    <StatusCard
      label="API 与数据依赖"
      :state="apiState"
    />
    <SearchDebugPanel
      knowledge-base-id="kb-demo-campus-merchants"
      :initial-results="sampleResults"
    />
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
