<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '@/router/auth-routing'

const route = useRoute()
const router = useRouter()

async function retry(): Promise<void> {
  await router.replace(safeRedirect(route.query.redirect) ?? '/')
}
</script>

<template>
  <main class="state-page">
    <span class="eyebrow">CONNECTION INTERRUPTED</span>
    <h1>暂时无法连接服务</h1>
    <p class="intro">
      登录信息仍保留在当前设备中。请检查网络后重试，无需重复输入账号密码。
    </p>
    <el-button
      type="primary"
      @click="retry"
    >
      重新连接
    </el-button>
  </main>
</template>
