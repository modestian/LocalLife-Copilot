<script setup lang="ts">
import ModelLifecycleWorkbench from '@/components/ModelLifecycleWorkbench.vue'
import ProductTopBar from '@/components/ProductTopBar.vue'
</script>

<template>
  <main class="model-management-page">
    <ProductTopBar active="admin" />
    <ModelLifecycleWorkbench />
  </main>
</template>

<style scoped>
.model-management-page { width: min(1160px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 80px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 18px; border-bottom: 1px solid #e8e8e8; padding-bottom: 22px; }
header a { color: #28231f; font-size: .76rem; font-weight: 900; letter-spacing: .07em; text-decoration: none; }
header div { display: flex; align-items: center; gap: 14px; color: #695b51; font-size: .78rem; }
header button { border: 0; padding: 6px; background: transparent; color: #9d3423; cursor: pointer; font-weight: 800; }
@media (max-width: 540px) { .model-management-page { width: min(100% - 28px, 620px); } header div span { display: none; } }
</style>
