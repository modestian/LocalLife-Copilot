<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'

import { getUserFacingError, toApiClientError } from '@/api/errors'
import { moderationApi } from '@/api/operations'
import type { SensitiveWordRule } from '@/types/operations'

type ScopeOption = 'INPUT' | 'OUTPUT' | 'BOTH'
type MatchTypeOption = 'CONTAINS' | 'EXACT'
type SeverityOption = 'LOW' | 'MEDIUM' | 'HIGH'

const rules = ref<SensitiveWordRule[]>([])
const loading = ref(false)
const submitting = ref(false)
const deletingId = ref('')
const enabledOnly = ref(true)
const forbidden = ref(false)
const errorMessage = ref('')
const notice = ref('')

const word = ref('')
const scope = ref<ScopeOption>('BOTH')
const matchType = ref<MatchTypeOption>('CONTAINS')
const severity = ref<SeverityOption>('HIGH')

const canSubmit = computed(() => word.value.trim().length > 0 && !submitting.value)

onMounted(() => {
  void loadRules()
})

async function loadRules(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await moderationApi.listSensitiveWords({ enabled_only: enabledOnly.value })
    rules.value = result.items
    forbidden.value = false
  } catch (err: unknown) {
    const apiError = toApiClientError(err)
    forbidden.value = apiError.status === 403
    errorMessage.value = forbidden.value
      ? '仅平台管理员可以管理违禁词规则'
      : getUserFacingError(err)
    rules.value = []
  } finally {
    loading.value = false
  }
}

function toggleEnabledOnly(): void {
  enabledOnly.value = !enabledOnly.value
  void loadRules()
}

async function addWord(): Promise<void> {
  const trimmed = word.value.trim()
  if (!trimmed) return

  notice.value = ''
  errorMessage.value = ''
  submitting.value = true
  try {
    const created = await moderationApi.createSensitiveWord({
      word: trimmed,
      scope: scope.value,
      match_type: matchType.value,
      severity: severity.value,
    })
    notice.value = `已添加违禁词「${created.word}」（第 ${created.version_no} 版）`
    word.value = ''
    await loadRules()
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err, '添加违禁词失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

async function removeRule(rule: SensitiveWordRule): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除后「${rule.word}」将不再拦截新提交的内容，确定删除吗？`,
      '删除违禁词',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  notice.value = ''
  errorMessage.value = ''
  deletingId.value = rule.id
  try {
    await moderationApi.deleteSensitiveWord(rule.id)
    notice.value = `已删除违禁词「${rule.word}」`
    await loadRules()
  } catch (err: unknown) {
    errorMessage.value = getUserFacingError(err, '删除违禁词失败，请稍后重试')
  } finally {
    deletingId.value = ''
  }
}

function scopeLabel(value: string): string {
  const map: Record<string, string> = {
    INPUT: '用户输入',
    OUTPUT: '模型输出',
    BOTH: '双向',
  }
  return map[value] ?? value
}

function matchTypeLabel(value: string): string {
  const map: Record<string, string> = {
    CONTAINS: '包含即拦截',
    EXACT: '完全匹配',
  }
  return map[value] ?? value
}

function severityLabel(value: string): string {
  const map: Record<string, string> = {
    LOW: '低',
    MEDIUM: '中',
    HIGH: '高',
  }
  return map[value] ?? value
}

function severityType(value: string): 'info' | 'warning' | 'danger' {
  const map: Record<string, 'info' | 'warning' | 'danger'> = {
    LOW: 'info',
    MEDIUM: 'warning',
    HIGH: 'danger',
  }
  return map[value] ?? 'info'
}
</script>

<template>
  <section class="sensitive-word-manager">
    <p class="intro">
      命中违禁词的评论会在提交时被直接拒绝。重复添加同一个词会生成新版本并停用旧版本。
    </p>

    <form
      class="word-form"
      @submit.prevent="addWord"
    >
      <el-input
        v-model="word"
        class="word-input"
        placeholder="输入违禁词，如：好评返现"
        :maxlength="200"
        show-word-limit
        :disabled="forbidden"
      />
      <el-select
        v-model="scope"
        class="word-select"
        :disabled="forbidden"
      >
        <el-option
          label="双向"
          value="BOTH"
        />
        <el-option
          label="用户输入"
          value="INPUT"
        />
        <el-option
          label="模型输出"
          value="OUTPUT"
        />
      </el-select>
      <el-select
        v-model="matchType"
        class="word-select"
        :disabled="forbidden"
      >
        <el-option
          label="包含即拦截"
          value="CONTAINS"
        />
        <el-option
          label="完全匹配"
          value="EXACT"
        />
      </el-select>
      <el-select
        v-model="severity"
        class="word-select"
        :disabled="forbidden"
      >
        <el-option
          label="高危"
          value="HIGH"
        />
        <el-option
          label="中危"
          value="MEDIUM"
        />
        <el-option
          label="低危"
          value="LOW"
        />
      </el-select>
      <el-button
        type="primary"
        native-type="submit"
        :loading="submitting"
        :disabled="!canSubmit || forbidden"
      >
        添加
      </el-button>
    </form>

    <p
      v-if="notice"
      class="notice"
    >
      {{ notice }}
    </p>
    <p
      v-if="errorMessage"
      class="error"
    >
      {{ errorMessage }}
    </p>

    <div class="list-toolbar">
      <button
        type="button"
        :class="['filter-btn', { active: enabledOnly }]"
        @click="toggleEnabledOnly"
      >
        {{ enabledOnly ? '仅显示生效规则' : '显示全部版本' }}
      </button>
      <span class="rule-count">共 {{ rules.length }} 条</span>
    </div>

    <div
      v-if="loading"
      class="loading"
    >
      加载中...
    </div>

    <div
      v-else-if="rules.length === 0"
      class="empty"
    >
      {{ forbidden ? '' : '暂无违禁词规则，添加后将立即生效' }}
    </div>

    <table
      v-else
      class="rule-table"
    >
      <thead>
        <tr>
          <th>违禁词</th>
          <th>作用方向</th>
          <th>匹配方式</th>
          <th>严重程度</th>
          <th>版本</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="rule in rules"
          :key="rule.id"
        >
          <td class="rule-word">
            {{ rule.word }}
          </td>
          <td>{{ scopeLabel(rule.scope) }}</td>
          <td>{{ matchTypeLabel(rule.match_type) }}</td>
          <td>
            <el-tag
              :type="severityType(rule.severity)"
              size="small"
            >
              {{ severityLabel(rule.severity) }}
            </el-tag>
          </td>
          <td>v{{ rule.version_no }}</td>
          <td>
            <el-tag
              :type="rule.enabled ? 'success' : 'info'"
              size="small"
            >
              {{ rule.enabled ? '生效中' : '已停用' }}
            </el-tag>
          </td>
          <td>
            <el-button
              v-if="rule.enabled"
              type="danger"
              size="small"
              link
              :loading="deletingId === rule.id"
              :disabled="forbidden"
              @click="removeRule(rule)"
            >
              删除
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.intro {
  color: #606266;
  margin-bottom: 16px;
}

.word-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.word-input {
  flex: 1 1 240px;
}

.word-select {
  width: 140px;
}

.notice {
  color: #67c23a;
  margin-bottom: 12px;
}

.error {
  color: #f56c6c;
  margin-bottom: 12px;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.filter-btn {
  padding: 6px 16px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}

.filter-btn.active {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}

.rule-count {
  font-size: 12px;
  color: #909399;
}

.loading,
.empty {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}

.rule-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.rule-table th,
.rule-table td {
  padding: 10px 12px;
  text-align: left;
  font-size: 14px;
  border-bottom: 1px solid #ebeef5;
}

.rule-table th {
  color: #909399;
  font-weight: 600;
  background: #fafafa;
}

.rule-table tbody tr:last-child td {
  border-bottom: none;
}

.rule-word {
  font-weight: 600;
}
</style>
