<script setup lang="ts">
import { useRouter } from 'vue-router'

import ModelLifecycleWorkbench from '@/components/ModelLifecycleWorkbench.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

async function logout(): Promise<void> {
  await authStore.logout()
  await router.replace({ name: 'root' })
}
</script>

<template>
  <main class="model-management-page">
    <header>
      <router-link to="/admin">
        LOCAL LIFE · AI COPILOT
      </router-link>
      <div>
        <span>{{ authStore.currentUser?.display_name }}</span>
        <button
          type="button"
          @click="logout"
        >
          退出登录
        </button>
      </div>
    </header>
    <ModelLifecycleWorkbench />
  </main>
</template>

<style scoped>
.model-management-page { width: min(1160px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 80px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 18px; border-bottom: 1px solid rgb(74 54 42 / 12%); padding-bottom: 22px; }
header a { color: var(--brand); font-size: .74rem; font-weight: 900; letter-spacing: .14em; text-decoration: none; }
header div { display: flex; align-items: center; gap: 14px; color: #695b51; font-size: .78rem; }
header button { border: 0; padding: 6px; background: transparent; color: #9d3423; cursor: pointer; font-weight: 800; }
@media (max-width: 540px) { .model-management-page { width: min(100% - 28px, 620px); } header div span { display: none; } }
</style>
