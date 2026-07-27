<script setup lang="ts">
import { computed } from 'vue'

import ProductTopBar from '@/components/ProductTopBar.vue'
import { useAuthStore } from '@/stores/auth'

interface WorkspaceEntry {
  to: string
  label: string
  description: string
}

const props = defineProps<{
  title: string
  description: string
  entry?: WorkspaceEntry
  entries?: WorkspaceEntry[]
}>()

const authStore = useAuthStore()
const workspaceEntries = computed(() => props.entries ?? (props.entry ? [props.entry] : []))
</script>

<template>
  <main class="home-page">
    <ProductTopBar active="admin" />
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
      v-for="workspaceEntry in workspaceEntries"
      :key="workspaceEntry.to"
      class="workspace-entry"
      :to="workspaceEntry.to"
    >
      <span>{{ workspaceEntry.label }} →</span>
      <small>{{ workspaceEntry.description }}</small>
    </router-link>
  </main>
</template>
