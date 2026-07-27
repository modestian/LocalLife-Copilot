<script setup lang="ts">
/* eslint-disable vue/no-v-html -- renderer escapes source before adding known-safe tags */
import { computed } from 'vue'

import { renderSafeMarkdown } from '@/utils/safe-markdown'

const props = defineProps<{ content: string }>()
const html = computed(() => renderSafeMarkdown(props.content))
</script>

<template>
  <!-- HTML is escaped before the restricted Markdown renderer adds known-safe tags. -->
  <div
    class="safe-markdown"
    v-html="html"
  />
</template>

<style scoped>
.safe-markdown { color: #41342c; font-size: .92rem; line-height: 1.72; overflow-wrap: anywhere; }
.safe-markdown :deep(p) { margin: 0 0 10px; }
.safe-markdown :deep(p:last-child) { margin-bottom: 0; }
.safe-markdown :deep(h1), .safe-markdown :deep(h2), .safe-markdown :deep(h3) { margin: 14px 0 8px; color: #2c211b; line-height: 1.35; }
.safe-markdown :deep(h1) { font-size: 1.25rem; }
.safe-markdown :deep(h2) { font-size: 1.1rem; }
.safe-markdown :deep(h3) { font-size: 1rem; }
.safe-markdown :deep(ul) { margin: 8px 0; padding-left: 22px; }
.safe-markdown :deep(code) { border-radius: 4px; padding: 2px 4px; background: #f2e8de; font-family: "Cascadia Code", Consolas, monospace; font-size: .84em; }
.safe-markdown :deep(pre) { overflow-x: auto; border-radius: 9px; padding: 12px; background: #302720; color: #fff8f0; }
.safe-markdown :deep(pre code) { padding: 0; background: transparent; color: inherit; }
.safe-markdown :deep(blockquote) { margin: 10px 0; border-left: 3px solid #d26b57; padding-left: 12px; color: #695b51; }
.safe-markdown :deep(a) { color: #a93a28; font-weight: 700; text-underline-offset: 3px; }
</style>
