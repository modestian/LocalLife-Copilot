<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  content: string
  highlight?: string
}>(), {
  highlight: '',
})

const parts = computed(() => {
  const target = props.highlight.trim()
  if (!target) return [{ text: props.content, highlighted: false }]
  const escapedTarget = target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const expressions = new RegExp(`(${escapedTarget})`, 'gi')
  return props.content
    .split(expressions)
    .filter(Boolean)
    .map((text) => ({ text, highlighted: text.toLocaleLowerCase() === target.toLocaleLowerCase() }))
})
</script>

<template>
  <span>
    <template
      v-for="(part, index) in parts"
      :key="`${index}-${part.text}`"
    >
      <mark v-if="part.highlighted">{{ part.text }}</mark>
      <span v-else>{{ part.text }}</span>
    </template>
  </span>
</template>

<style scoped>
mark { border-radius: 3px; padding: 1px 2px; background: #ffe2a8; color: #3b2b21; }
</style>
