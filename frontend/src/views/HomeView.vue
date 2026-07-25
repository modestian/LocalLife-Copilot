<script setup lang="ts">
import { ref } from 'vue'

import ConversationWorkspace from '@/components/ConversationWorkspace.vue'
import ProductTopBar from '@/components/ProductTopBar.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
// Public chat always uses the server-resolved shared corpus (all USER+READ knowledge bases).
// Passing specific IDs from user resource_scopes would risk stale / deleted grants.
const knowledgeBaseIds = ref<string[]>([])

</script>

<template>
  <main class="home-page">
    <ProductTopBar active="discover" />
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
    <ConversationWorkspace
      :knowledge-base-ids="knowledgeBaseIds"
      :read-only="!authStore.isAuthenticated"
    />
  </main>
</template>
