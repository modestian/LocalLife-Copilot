<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { getUserFacingError } from '@/api/errors'
import { modelLifecycleApi } from '@/api/model-lifecycle'
import type {
  FineTuningJob,
  FineTuningMethod,
  ModelDeployment,
  ModelLifecycleApi,
  ModelVersion,
  ModelVersionStatus,
  TrainingDataset,
} from '@/types/model-lifecycle'

const props = withDefaults(defineProps<{
  api?: ModelLifecycleApi
  initialModels?: ModelVersion[]
}>(), {
  api: () => modelLifecycleApi,
  initialModels: () => [],
})

type NoticeLevel = 'success' | 'error' | 'warning'

const datasetId = ref('')
const selectedDataset = ref<TrainingDataset | null>(null)
const jobId = ref('')
const selectedJob = ref<FineTuningJob | null>(null)
const models = ref<ModelVersion[]>([...props.initialModels])
const selectedModelId = ref(props.initialModels[0]?.id ?? '')
const busy = ref(false)
const notice = ref('')
const noticeLevel = ref<NoticeLevel>('success')
const evaluationConfirmed = ref(false)
const deployConfirmed = ref(false)
const approvalConfirmed = ref(false)
const rollbackConfirmed = ref(false)
const deployments = ref<ModelDeployment[]>([])
const lastReceipt = ref<ModelDeployment | null>(null)
const deployment = reactive({
  scene: 'merchant_analytics',
  environment: 'staging',
  trafficPercent: 10,
  reason: '',
})
const approval = reactive({
  status: 'APPROVED' as Exclude<ModelVersionStatus, 'REGISTERED'>,
  reason: '',
})
const rollback = reactive({
  scene: 'merchant_analytics',
  environment: 'staging',
  reason: '',
})
const datasetDraft = reactive({
  name: 'sentiment-feedback-dataset',
  taskType: 'sentiment_classification',
  rating: 'negative',
  trainPercent: 80,
  validationPercent: 10,
  testPercent: 10,
  isolationKey: 'CONVERSATION' as const,
})
const trainingDraft = reactive({
  baseModelId: 'chinese-roberta-base',
  method: 'LORA' as FineTuningMethod,
  r: 8,
  loraAlpha: 16,
  loraDropout: 0.05,
  learningRate: 0.0002,
  epochs: 3,
  batchSize: 16,
  seed: 42,
})

const selectedModel = computed(
  () => models.value.find((model) => model.id === selectedModelId.value) ?? null,
)
const datasetReady = computed(() => selectedDataset.value?.status === 'READY')
const canCancelJob = computed(
  () => selectedJob.value?.status === 'PENDING' || selectedJob.value?.status === 'RUNNING',
)
const canEvaluateJob = computed(() => selectedJob.value?.status === 'SUCCEEDED')
const canRegisterModel = computed(
  () => selectedJob.value?.status === 'SUCCEEDED' && evaluationConfirmed.value,
)
const canDeploy = computed(
  () =>
    selectedModel.value?.status === 'APPROVED' &&
    deployConfirmed.value &&
    deployment.trafficPercent >= 1 &&
    deployment.trafficPercent <= 100 &&
    deployment.reason.trim().length > 0,
)
type ApprovableStatus = Exclude<ModelVersionStatus, 'REGISTERED'>

const approvalTargets = computed<ApprovableStatus[]>(() => {
  switch (selectedModel.value?.status) {
    case 'REGISTERED':
      return ['EVALUATED', 'ARCHIVED']
    case 'EVALUATED':
      return ['APPROVED', 'REJECTED', 'ARCHIVED']
    case 'APPROVED':
    case 'REJECTED':
      return ['ARCHIVED']
    default:
      return []
  }
})
const canApprove = computed(
  () =>
    approvalTargets.value.length > 0 &&
    approval.reason.trim().length > 0 &&
    approvalConfirmed.value,
)
const canRollback = computed(
  () =>
    Boolean(selectedModel.value) &&
    rollback.scene.trim().length > 0 &&
    rollback.environment.trim().length > 0 &&
    rollback.reason.trim().length > 0 &&
    rollbackConfirmed.value,
)

const datasetStatusLabels: Record<TrainingDataset['status'], string> = {
  BUILDING: '构建中',
  READY: '已固化',
  REJECTED: '已拒绝',
  ARCHIVED: '已归档',
}
const jobStatusLabels: Record<FineTuningJob['status'], string> = {
  PENDING: '等待执行',
  RUNNING: '训练中',
  SUCCEEDED: '训练成功',
  FAILED: '训练失败',
  CANCELLED: '已取消',
}
const modelStatusLabels: Record<ModelVersion['status'], string> = {
  REGISTERED: '已登记',
  EVALUATED: '已评测',
  APPROVED: '已审批',
  REJECTED: '已拒绝',
  ARCHIVED: '已归档',
}

watch(
  () => props.initialModels,
  (value) => {
    models.value = [...value]
    if (!selectedModelId.value) selectedModelId.value = value[0]?.id ?? ''
  },
)

watch(approvalTargets, (targets) => {
  if (!targets.includes(approval.status)) {
    approval.status = targets[0] ?? 'APPROVED'
  }
}, { immediate: true })

function notify(message: string, level: NoticeLevel): void {
  notice.value = message
  noticeLevel.value = level
}

function clearNotice(): void {
  notice.value = ''
}

function asError(error: unknown, fallback: string): void {
  notify(getUserFacingError(error, fallback), 'error')
}

async function loadDataset(): Promise<void> {
  if (!datasetId.value.trim()) {
    notify('请输入已固化数据集 ID 后再查询。', 'warning')
    return
  }
  busy.value = true
  clearNotice()
  try {
    selectedDataset.value = await props.api.getDataset(datasetId.value.trim())
    datasetId.value = selectedDataset.value.id
    notify('已加载数据集详情。', 'success')
  } catch (error) {
    asError(error, '数据集详情加载失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function createDataset(): Promise<void> {
  const splitTotal = datasetDraft.trainPercent + datasetDraft.validationPercent + datasetDraft.testPercent
  if (splitTotal !== 100) {
    notify('训练、验证和测试切分比例之和必须为 100%。', 'warning')
    return
  }
  busy.value = true
  clearNotice()
  try {
    const ratings = datasetDraft.rating === 'all'
      ? undefined
      : [datasetDraft.rating === 'positive' ? 1 : -1] as Array<-1 | 1>
    selectedDataset.value = await props.api.createDataset({
      name: datasetDraft.name.trim(),
      task_type: datasetDraft.taskType.trim(),
      filters: {
        ...(ratings ? { ratings } : {}),
        reviewed_only: true,
      },
      split_config: {
        train_percent: datasetDraft.trainPercent,
        validation_percent: datasetDraft.validationPercent,
        test_percent: datasetDraft.testPercent,
        isolation_key: datasetDraft.isolationKey,
      },
    })
    datasetId.value = selectedDataset.value.id
    notify('数据集构建任务已创建；只有状态为“已固化”时才可开始训练。', 'success')
  } catch (error) {
    asError(error, '数据集构建提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function createJob(): Promise<void> {
  if (!selectedDataset.value || !datasetReady.value) {
    notify('请先加载一个状态为“已固化”的数据集。', 'warning')
    return
  }
  busy.value = true
  clearNotice()
  try {
    selectedJob.value = await props.api.createJob({
      task_type: selectedDataset.value.task_type,
      base_model_id: trainingDraft.baseModelId.trim(),
      dataset_id: selectedDataset.value.id,
      method: trainingDraft.method,
      hyperparameters: {
        r: trainingDraft.r,
        lora_alpha: trainingDraft.loraAlpha,
        lora_dropout: trainingDraft.loraDropout,
        learning_rate: trainingDraft.learningRate,
        epochs: trainingDraft.epochs,
        batch_size: trainingDraft.batchSize,
        seed: trainingDraft.seed,
      },
    })
    jobId.value = selectedJob.value.id
    evaluationConfirmed.value = false
    notify('训练任务已创建。', 'success')
  } catch (error) {
    asError(error, '训练任务提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function loadJob(): Promise<void> {
  if (!jobId.value.trim()) {
    notify('请输入训练任务 ID 后再查询。', 'warning')
    return
  }
  busy.value = true
  clearNotice()
  try {
    selectedJob.value = await props.api.getJob(jobId.value.trim())
    jobId.value = selectedJob.value.id
    notify('已加载训练任务详情。', 'success')
  } catch (error) {
    asError(error, '训练任务详情加载失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function cancelJob(): Promise<void> {
  if (!selectedJob.value || !canCancelJob.value) return
  busy.value = true
  clearNotice()
  try {
    selectedJob.value = await props.api.cancelJob(selectedJob.value.id)
    notify('已提交取消训练任务。', 'success')
  } catch (error) {
    asError(error, '训练任务取消失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function evaluateJob(): Promise<void> {
  if (!selectedJob.value || !canEvaluateJob.value) return
  busy.value = true
  clearNotice()
  try {
    selectedJob.value = await props.api.evaluateJob(selectedJob.value.id)
    notify('已提交固定测试集评测，请核验基线与 LoRA 指标。', 'success')
  } catch (error) {
    asError(error, '训练任务评测提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function registerModel(): Promise<void> {
  if (!selectedJob.value || !canRegisterModel.value) return
  busy.value = true
  clearNotice()
  try {
    const model = await props.api.registerModel(selectedJob.value.id)
    models.value = [...models.value.filter((item) => item.id !== model.id), model]
    selectedModelId.value = model.id
    notify('模型已登记；登记状态不等于审批通过，尚不可部署。', 'success')
  } catch (error) {
    asError(error, '模型登记失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function refreshModels(): Promise<void> {
  models.value = await props.api.listModels()
  if (!models.value.some((model) => model.id === selectedModelId.value)) {
    selectedModelId.value = models.value[0]?.id ?? ''
  }
}

async function refreshDeployments(): Promise<void> {
  const scene = rollback.scene.trim()
  const environment = rollback.environment.trim()
  if (!scene || !environment) return
  deployments.value = await props.api.listDeployments({ scene, environment })
}

async function loadModels(): Promise<void> {
  busy.value = true
  clearNotice()
  try {
    await refreshModels()
    notify(models.value.length ? '已加载模型版本。' : '当前没有可显示的模型版本。', 'success')
  } catch (error) {
    asError(error, '模型列表加载失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function deployModel(): Promise<void> {
  if (!selectedModel.value || !canDeploy.value) return
  busy.value = true
  clearNotice()
  try {
    await props.api.deployModel(selectedModel.value.id, {
      scene: deployment.scene.trim(),
      environment: deployment.environment.trim(),
      traffic_percent: deployment.trafficPercent,
      reason: deployment.reason.trim(),
    })
    deployConfirmed.value = false
    await refreshDeployments()
    notify('部署请求已提交；服务端仍需校验场景内灰度比例总和与唯一全量 ACTIVE 版本。', 'success')
  } catch (error) {
    asError(error, '模型部署提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function submitApproval(): Promise<void> {
  if (!selectedModel.value || !canApprove.value) return
  busy.value = true
  clearNotice()
  try {
    const reason = approval.reason.trim()
    await props.api.updateModelStatus(selectedModel.value.id, {
      status: approval.status,
      reason,
    })
    approval.reason = ''
    approvalConfirmed.value = false
    await refreshModels()
    lastReceipt.value = null
    notify(`审批结论已提交：${modelStatusLabels[approval.status]}；模型列表与审计状态已刷新。`, 'success')
  } catch (error) {
    asError(error, '模型审批提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

async function submitRollback(): Promise<void> {
  if (!selectedModel.value || !canRollback.value) return
  busy.value = true
  clearNotice()
  try {
    lastReceipt.value = await props.api.rollbackModel(selectedModel.value.id, {
      scene: rollback.scene.trim(),
      environment: rollback.environment.trim(),
      reason: rollback.reason.trim(),
    })
    rollback.reason = ''
    rollbackConfirmed.value = false
    await Promise.all([refreshModels(), refreshDeployments()])
    notify('回滚已执行；模型、部署与审计状态已刷新。', 'success')
  } catch (error) {
    asError(error, '模型回滚提交失败，请稍后重试。')
  } finally {
    busy.value = false
  }
}

function metricEntries(metrics?: Record<string, number | string | null> | null): Array<[string, number | string | null]> {
  return Object.entries(metrics ?? {})
}
</script>

<template>
  <section class="model-lifecycle">
    <header class="model-lifecycle__header">
      <div>
        <span class="eyebrow">MODEL GOVERNANCE</span>
        <h2>数据集、训练与安全发布</h2>
        <p>从已授权反馈构建不可变数据集，追踪 LoRA 训练证据，并只对已审批版本开放发布。</p>
      </div>
      <button
        type="button"
        :disabled="busy"
        @click="loadModels"
      >
        刷新模型版本
      </button>
    </header>

    <p
      v-if="notice"
      :class="['model-lifecycle__notice', `is-${noticeLevel}`]"
      :role="noticeLevel === 'error' ? 'alert' : 'status'"
    >
      {{ notice }}
    </p>

    <div class="model-lifecycle__grid">
      <article class="model-panel">
        <header>
          <span>01</span>
          <div>
            <h3>不可变数据集</h3>
            <p>仅导出已授权、已审核的反馈；按会话或实体隔离切分。</p>
          </div>
        </header>
        <form @submit.prevent="createDataset">
          <label>
            数据集名称
            <input v-model="datasetDraft.name">
          </label>
          <label>
            训练任务类型
            <input v-model="datasetDraft.taskType">
          </label>
          <label>
            反馈筛选
            <select v-model="datasetDraft.rating">
              <option value="negative">仅负向反馈</option>
              <option value="positive">仅正向反馈</option>
              <option value="all">全部有效反馈</option>
            </select>
          </label>
          <div class="model-lifecycle__split">
            <label>训练 %<input
              v-model.number="datasetDraft.trainPercent"
              min="1"
              max="98"
              type="number"
            ></label>
            <label>验证 %<input
              v-model.number="datasetDraft.validationPercent"
              min="1"
              max="98"
              type="number"
            ></label>
            <label>测试 %<input
              v-model.number="datasetDraft.testPercent"
              min="1"
              max="98"
              type="number"
            ></label>
          </div>
          <label>
            隔离键
            <select v-model="datasetDraft.isolationKey">
              <option value="CONVERSATION">按会话隔离</option>
              <option value="ENTITY">按实体隔离</option>
            </select>
          </label>
          <button
            type="submit"
            :disabled="busy"
          >
            创建数据集
          </button>
        </form>
        <div class="model-lifecycle__lookup">
          <input
            v-model="datasetId"
            placeholder="输入数据集 ID 查询详情"
          >
          <button
            type="button"
            :disabled="busy"
            @click="loadDataset"
          >
            校验数据集
          </button>
        </div>
        <section
          v-if="selectedDataset"
          class="model-lifecycle__detail"
        >
          <div class="model-lifecycle__status-row">
            <strong>{{ selectedDataset.name }}</strong>
            <span :class="['status-chip', `is-${selectedDataset.status.toLowerCase()}`]">
              {{ datasetStatusLabels[selectedDataset.status] }}
            </span>
          </div>
          <dl>
            <div><dt>SHA-256</dt><dd>{{ selectedDataset.dataset_hash }}</dd></div>
            <div><dt>样本量</dt><dd>{{ selectedDataset.sample_count }}</dd></div>
            <div><dt>脱敏规则</dt><dd>{{ selectedDataset.redaction_version }}</dd></div>
          </dl>
          <small v-if="selectedDataset.status === 'READY'">数据集已固化，不允许修改内容；如需调整筛选条件，请创建新版本。</small>
        </section>
      </article>

      <article class="model-panel">
        <header>
          <span>02</span>
          <div>
            <h3>LoRA 训练与评测</h3>
            <p>仅允许 READY 数据集和白名单基础模型，前端不上传训练脚本。</p>
          </div>
        </header>
        <form @submit.prevent="createJob">
          <label>
            基础模型 ID
            <input v-model="trainingDraft.baseModelId">
          </label>
          <label>
            方法
            <select v-model="trainingDraft.method"><option value="LORA">LoRA</option><option value="QLORA">QLoRA</option></select>
          </label>
          <div class="model-lifecycle__split">
            <label>r<input
              v-model.number="trainingDraft.r"
              min="1"
              type="number"
            ></label>
            <label>alpha<input
              v-model.number="trainingDraft.loraAlpha"
              min="1"
              type="number"
            ></label>
            <label>dropout<input
              v-model.number="trainingDraft.loraDropout"
              min="0"
              max="1"
              step="0.01"
              type="number"
            ></label>
          </div>
          <div class="model-lifecycle__split">
            <label>学习率<input
              v-model.number="trainingDraft.learningRate"
              min="0.000001"
              step="0.000001"
              type="number"
            ></label>
            <label>epochs<input
              v-model.number="trainingDraft.epochs"
              min="1"
              type="number"
            ></label>
            <label>batch<input
              v-model.number="trainingDraft.batchSize"
              min="1"
              type="number"
            ></label>
          </div>
          <label>
            随机种子
            <input
              v-model.number="trainingDraft.seed"
              min="0"
              type="number"
            >
          </label>
          <button
            type="submit"
            :disabled="busy || !datasetReady"
          >
            创建训练任务
          </button>
        </form>
        <div class="model-lifecycle__lookup">
          <input
            v-model="jobId"
            placeholder="输入训练任务 ID 查询详情"
          >
          <button
            type="button"
            :disabled="busy"
            @click="loadJob"
          >
            刷新任务
          </button>
        </div>
        <section
          v-if="selectedJob"
          class="model-lifecycle__detail"
        >
          <div class="model-lifecycle__status-row">
            <strong>{{ selectedJob.method }} / {{ selectedJob.base_model_id }}</strong>
            <span :class="['status-chip', `is-${selectedJob.status.toLowerCase()}`]">{{ jobStatusLabels[selectedJob.status] }}</span>
          </div>
          <progress
            :value="selectedJob.progress"
            max="100"
            :aria-label="`训练进度 ${selectedJob.progress}%`"
          />
          <small>进度 {{ selectedJob.progress }}% <template v-if="selectedJob.logs_uri">· 日志：{{ selectedJob.logs_uri }}</template></small>
          <p
            v-if="selectedJob.error_message"
            class="model-lifecycle__failure"
          >
            {{ selectedJob.error_code }}：{{ selectedJob.error_message }}
          </p>
          <div class="model-lifecycle__actions">
            <button
              type="button"
              :disabled="busy || !canCancelJob"
              @click="cancelJob"
            >
              取消训练
            </button>
            <button
              type="button"
              :disabled="busy || !canEvaluateJob"
              @click="evaluateJob"
            >
              固定集评测
            </button>
          </div>
          <label
            v-if="canEvaluateJob"
            class="model-lifecycle__confirm"
          >
            <input
              v-model="evaluationConfirmed"
              type="checkbox"
            >
            已核验基线/LoRA 同集指标、负面召回与人工抽检结论。
          </label>
          <button
            type="button"
            :disabled="busy || !canRegisterModel"
            @click="registerModel"
          >
            通过门禁并登记模型
          </button>
        </section>
      </article>
    </div>

    <article class="model-panel model-panel--wide">
      <header>
        <span>03</span>
        <div>
          <h3>模型卡、审批与灰度发布</h3>
          <p>只有 APPROVED 模型可以提交部署；全量、审批与回滚均需要服务端状态机和审计。</p>
        </div>
      </header>
      <div class="model-lifecycle__model-grid">
        <section>
          <label>
            模型版本
            <select v-model="selectedModelId">
              <option value="">请选择模型版本</option>
              <option
                v-for="model in models"
                :key="model.id"
                :value="model.id"
              >
                {{ model.name }} / {{ model.version }} / {{ modelStatusLabels[model.status] }}
              </option>
            </select>
          </label>
          <div
            v-if="selectedModel"
            class="model-lifecycle__card"
          >
            <div class="model-lifecycle__status-row">
              <strong>{{ selectedModel.name }} {{ selectedModel.version }}</strong>
              <span :class="['status-chip', `is-${selectedModel.status.toLowerCase()}`]">{{ modelStatusLabels[selectedModel.status] }}</span>
            </div>
            <dl>
              <div><dt>基础模型</dt><dd>{{ selectedModel.base_model_ref }}</dd></div>
              <div><dt>产物 SHA-256</dt><dd>{{ selectedModel.artifact_sha256 || '等待登记结果' }}</dd></div>
              <div><dt>Adapter</dt><dd>{{ selectedModel.adapter_uri || '等待登记结果' }}</dd></div>
              <div><dt>数据集 Hash</dt><dd>{{ selectedModel.card?.dataset_hash || '接口尚未返回' }}</dd></div>
            </dl>
            <div
              v-if="metricEntries(selectedModel.metrics ?? selectedModel.card?.metrics).length"
              class="model-lifecycle__metrics"
            >
              <span
                v-for="[name, value] in metricEntries(selectedModel.metrics ?? selectedModel.card?.metrics)"
                :key="name"
              >{{ name }}：{{ value }}</span>
            </div>
            <p v-if="selectedModel.card?.human_review_summary">
              人工抽检：{{ selectedModel.card.human_review_summary }}
            </p>
            <p v-if="selectedModel.card?.limitations?.length">
              限制：{{ selectedModel.card.limitations.join('；') }}
            </p>
          </div>
          <p
            v-else
            class="model-lifecycle__empty"
          >
            加载模型列表或从训练任务登记模型后，在此查看模型卡。
          </p>
        </section>

        <div class="model-lifecycle__deploy">
          <form @submit.prevent="deployModel">
            <label>场景<input v-model="deployment.scene"></label>
            <label>环境<input v-model="deployment.environment"></label>
            <label>灰度流量 %<input
              v-model.number="deployment.trafficPercent"
              min="1"
              max="100"
              type="number"
            ></label>
            <label>变更原因<textarea
              v-model="deployment.reason"
              maxlength="500"
              placeholder="记录发布目的、风险与验证范围"
            /></label>
            <label class="model-lifecycle__confirm">
              <input
                v-model="deployConfirmed"
                type="checkbox"
              >
              我确认此版本已审批，且已核对灰度总和、监控和回滚预案。
            </label>
            <button
              type="submit"
              :disabled="busy || !canDeploy"
            >
              提交灰度/全量发布
            </button>
          </form>

          <form
            class="model-lifecycle__subsection"
            @submit.prevent="submitApproval"
          >
            <h4>人工审批</h4>
            <label>审批结论
              <select
                v-model="approval.status"
                :disabled="!approvalTargets.length"
              >
                <option
                  v-for="target in approvalTargets"
                  :key="target"
                  :value="target"
                >
                  {{ modelStatusLabels[target] }}
                </option>
              </select>
            </label>
            <label>审批原因<textarea
              v-model="approval.reason"
              maxlength="500"
              placeholder="记录审批依据、评测结论与风险"
            /></label>
            <label class="model-lifecycle__confirm">
              <input
                v-model="approvalConfirmed"
                type="checkbox"
              >
              我确认已核验模型卡、固定集指标与人工抽检结论。
            </label>
            <button
              type="submit"
              :disabled="busy || !canApprove"
            >
              提交审批结论
            </button>
            <small v-if="selectedModel && !approvalTargets.length">当前模型状态为「{{ modelStatusLabels[selectedModel.status] }}」，没有可用的审批流转。</small>
          </form>

          <form
            class="model-lifecycle__subsection"
            @submit.prevent="submitRollback"
          >
            <h4>一键回滚</h4>
            <label>目标场景<input v-model="rollback.scene"></label>
            <label>目标环境<input v-model="rollback.environment"></label>
            <label>回滚原因<textarea
              v-model="rollback.reason"
              maxlength="500"
              placeholder="记录回滚触发原因与影响范围"
            /></label>
            <label class="model-lifecycle__confirm">
              <input
                v-model="rollbackConfirmed"
                type="checkbox"
              >
              我确认将「{{ rollback.scene.trim() || '未填写' }}」场景的「{{ rollback.environment.trim() || '未填写' }}」环境回滚至当前选中版本。
            </label>
            <button
              type="submit"
              :disabled="busy || !canRollback"
            >
              提交回滚
            </button>
            <small>回滚会把目标场景/环境的流量恢复至选中版本，服务端将写入 MODEL_ROLLBACK 审计。</small>
          </form>

          <section class="model-lifecycle__subsection model-lifecycle__receipt">
            <div class="model-lifecycle__receipt-header">
              <h4>部署与审计状态</h4>
              <button
                type="button"
                :disabled="busy"
                @click="refreshDeployments"
              >
                刷新部署状态
              </button>
            </div>
            <p v-if="lastReceipt">
              最近回执：{{ lastReceipt.action ?? 'DEPLOY' }} / {{ lastReceipt.status }}<template v-if="lastReceipt.result">
                / {{ lastReceipt.result }}
              </template>
            </p>
            <ul v-if="deployments.length">
              <li
                v-for="item in deployments"
                :key="item.deployment_id ?? item.id"
              >
                {{ item.model_version_id }} · {{ item.status }} · {{ item.traffic_percent }}%
              </li>
            </ul>
            <small v-else>提交发布或回滚后，在此查看场景「{{ rollback.scene.trim() || '未填写' }}」/ 环境「{{ rollback.environment.trim() || '未填写' }}」的部署与操作回执。</small>
          </section>
        </div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.model-lifecycle { display: grid; gap: 18px; margin-top: 30px; }
.model-lifecycle__header, .model-panel > header, .model-lifecycle__status-row, .model-lifecycle__actions { display: flex; align-items: center; gap: 12px; }
.model-lifecycle__header { justify-content: space-between; padding: 4px 2px; }
.model-lifecycle h2, .model-lifecycle h3, .model-lifecycle p { margin: 0; }
.model-lifecycle h2 { margin-top: 7px; color: #392d26; font-size: 1.65rem; }
.model-lifecycle__header p, .model-panel header p, .model-lifecycle small { color: #88776c; line-height: 1.55; }
.model-lifecycle button { min-height: 36px; border: 1px solid var(--brand); border-radius: 8px; padding: 7px 12px; background: var(--brand); color: #fff; cursor: pointer; font-weight: 800; }
.model-lifecycle button:disabled { cursor: not-allowed; opacity: .5; }
.model-lifecycle__notice { margin: 0; border-radius: 9px; padding: 10px 12px; font-size: .86rem; }
.model-lifecycle__notice.is-success { background: #ecfdf3; color: #166534; }.model-lifecycle__notice.is-warning { background: #fffbeb; color: #92400e; }.model-lifecycle__notice.is-error { background: #fff1f2; color: #b91c1c; }
.model-lifecycle__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.model-panel { display: grid; gap: 16px; border: 1px solid rgb(74 54 42 / 14%); border-radius: 15px; padding: 20px; background: rgb(255 255 255 / 74%); }
.model-panel > header > span { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 50%; background: #f6e9e2; color: var(--brand); font-size: .78rem; font-weight: 900; }.model-panel h3 { color: #392d26; font-size: 1rem; }.model-panel header p { margin-top: 3px; font-size: .76rem; }
.model-panel form { display: grid; gap: 10px; }.model-panel label { display: grid; gap: 5px; color: #695b51; font-size: .74rem; font-weight: 800; }.model-panel input, .model-panel select, .model-panel textarea { width: 100%; min-height: 37px; border: 1px solid #d9ccc1; border-radius: 8px; box-sizing: border-box; padding: 7px 9px; background: #fffdfa; color: #392d26; font: inherit; }.model-panel textarea { min-height: 84px; resize: vertical; }
.model-lifecycle__split { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }.model-lifecycle__lookup { display: grid; grid-template-columns: 1fr auto; gap: 8px; }.model-lifecycle__lookup input { min-height: 36px; border: 1px solid #d9ccc1; border-radius: 8px; padding: 7px 9px; background: #fffdfa; }
.model-lifecycle__detail, .model-lifecycle__card { display: grid; gap: 10px; border-top: 1px solid rgb(74 54 42 / 12%); padding-top: 14px; }.model-lifecycle__status-row { justify-content: space-between; color: #392d26; }.status-chip { border-radius: 999px; padding: 3px 8px; background: #f1f5f9; color: #475569; font-size: .7rem; font-weight: 800; }.status-chip.is-ready, .status-chip.is-succeeded, .status-chip.is-approved { background: #dcfce7; color: #166534; }.status-chip.is-failed, .status-chip.is-rejected { background: #ffe4e6; color: #be123c; }.status-chip.is-running, .status-chip.is-evaluated { background: #dbeafe; color: #1d4ed8; }
.model-lifecycle dl { display: grid; gap: 7px; margin: 0; }.model-lifecycle dl div { display: grid; grid-template-columns: minmax(80px, .8fr) minmax(0, 2fr); gap: 10px; }.model-lifecycle dt { color: #88776c; font-size: .7rem; }.model-lifecycle dd { overflow-wrap: anywhere; margin: 0; color: #4a362a; font-size: .76rem; }.model-lifecycle progress { width: 100%; height: 8px; accent-color: var(--brand); }.model-lifecycle__failure { color: #b91c1c; font-size: .8rem; }.model-lifecycle__actions { flex-wrap: wrap; }.model-lifecycle__actions button { border-color: #d9ccc1; background: #fffdfa; color: #695b51; }.model-lifecycle__confirm { grid-template-columns: auto 1fr; align-items: start; }.model-lifecycle__confirm input { width: auto; min-height: auto; margin-top: 3px; }.model-panel--wide { grid-column: 1 / -1; }.model-lifecycle__model-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(280px, .9fr); gap: 22px; }.model-lifecycle__model-grid > section { display: grid; align-content: start; gap: 14px; }.model-lifecycle__deploy { display: grid; align-content: start; gap: 16px; border-left: 1px solid rgb(74 54 42 / 12%); padding-left: 22px; }.model-lifecycle__subsection { display: grid; gap: 10px; border-top: 1px solid rgb(74 54 42 / 12%); padding-top: 14px; }.model-lifecycle__subsection h4 { margin: 0; color: #392d26; font-size: .88rem; }.model-lifecycle__receipt-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.model-lifecycle__receipt ul { display: grid; gap: 5px; margin: 0; padding-left: 18px; color: #4a362a; font-size: .76rem; }.model-lifecycle__metrics { display: flex; flex-wrap: wrap; gap: 7px; }.model-lifecycle__metrics span { border-radius: 5px; padding: 4px 7px; background: #f6eee9; color: #695b51; font-size: .72rem; }.model-lifecycle__empty { color: #88776c; font-size: .8rem; }
@media (max-width: 840px) { .model-lifecycle__grid, .model-lifecycle__model-grid { grid-template-columns: 1fr; }.model-lifecycle__deploy { border-top: 1px solid rgb(74 54 42 / 12%); border-left: 0; padding-top: 18px; padding-left: 0; } }
@media (max-width: 540px) { .model-lifecycle__header { align-items: flex-start; flex-direction: column; }.model-lifecycle__header > button { width: 100%; }.model-lifecycle__split { grid-template-columns: 1fr; }.model-lifecycle__lookup { grid-template-columns: 1fr; } }
</style>
