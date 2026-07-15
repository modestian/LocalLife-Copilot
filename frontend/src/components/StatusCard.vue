<script setup lang="ts">
defineProps<{
  label: string
  state: 'checking' | 'ready' | 'unavailable'
}>()
</script>

<template>
  <section
    class="status-card"
    :data-state="state"
  >
    <span
      class="status-dot"
      aria-hidden="true"
    />
    <div>
      <strong>{{ label }}</strong>
      <p>{{ state === 'checking' ? '检查中' : state === 'ready' ? '运行正常' : '暂不可用' }}</p>
    </div>
  </section>
</template>
