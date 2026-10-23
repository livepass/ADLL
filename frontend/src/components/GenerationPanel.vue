<template>
  <div class="panel">
    <h3>生成执行</h3>

    <p v-if="runtime.testing" class="banner banner-testing inline-banner">
      离线测试：本页生成的方案由 Mock 合成，不会发送源码、不调用任何外部 AI。
    </p>

    <div class="row">
      <button type="button" :disabled="startDisabled" @click="start">
        {{ runtime.testing ? '离线合成生成（Mock）' : '发起真实生成' }}
      </button>
      <button
        v-if="isRunning"
        type="button"
        class="danger"
        :disabled="cancelling"
        @click="cancel"
      >
        {{ cancelling ? '取消受理中…' : '请求取消' }}
      </button>
      <span v-if="isRunning" class="muted">轮询状态（1s）；无伪造 SSE 进度。</span>
    </div>
    <p v-if="startDisabledReason" class="muted">{{ startDisabledReason }}</p>

    <label class="stack-tight">
      随本次生成的反馈（可选，逐条作为 feedback 数据类型发送）
      <textarea v-model="feedbackText" rows="2" :disabled="starting"></textarea>
    </label>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <template v-if="detail">
      <dl class="exec-meta">
        <dt>execution</dt>
        <dd>#{{ detail.execution.id }}</dd>
        <dt>状态</dt>
        <dd><span class="chip" :class="statusClass">{{ detail.execution.status }}</span></dd>
        <dt>provider</dt>
        <dd>
          <span v-if="detail.execution.provider === 'mock'" class="chip warn">mock（合成，非真实）</span>
          <span v-else>{{ detail.execution.provider || '未知' }}</span>
        </dd>
        <dt>取消结果</dt>
        <dd>{{ cancelLabel }}</dd>
        <dt>失败原因</dt>
        <dd>{{ failureLabel }}</dd>
      </dl>

      <UsageCost :execution="detail.execution" />

      <div v-if="snapshot" class="snapshot">
        <h4>发送快照（授权子集与排除）</h4>
        <p class="muted">snapshot_digest <span class="hash">{{ snapshot.digest }}</span></p>
        <p>授权路径：{{ snapshot.authorized_paths.join(', ') || '默认' }}</p>
        <p>实际进入请求的文本文件：{{ snapshot.files.join(', ') || '（无）' }}</p>
        <p v-if="snapshot.snapshot_files && snapshot.snapshot_files.join(',') !== snapshot.files.join(',')" class="muted">
          快照原始文件：{{ snapshot.snapshot_files.join(', ') || '（无）' }}
        </p>
        <ul class="entries">
          <li v-for="item in snapshot.excluded" :key="item.path" class="mono">
            排除 {{ item.path }} — {{ item.reason }}
          </li>
        </ul>
        <p v-for="warning in snapshot.warnings" :key="warning" class="muted">
          属性判定：{{ warning }}
        </p>
        <p v-if="snapshot.lfs_pointers.length" class="warning">
          LFS 指针（不发送）：{{ snapshot.lfs_pointers.join(', ') }}
        </p>
        <p class="muted">
          快照/授权文件/实际请求的对应关系以服务端 send-audit 为准；取消仅在发送前生效。
        </p>
      </div>

      <div class="row">
        <button type="button" :disabled="auditBusy || !detail" @click="loadAudit">
          查看出站审计
        </button>
      </div>
      <div v-if="audits.length">
        <article v-for="audit in audits" :key="audit.id" class="audit">
          <p class="muted">
            audit #{{ audit.id }} · {{ audit.phase || 'confirmed_sent' }} ·
            authorization={{ audit.authorization_id ?? '—' }}
            <span v-if="audit.error_code"> · error={{ audit.error_code }}</span>
          </p>
          <p>content_digest（manifest） <span class="hash">{{ audit.content_digest }}</span></p>
          <p v-if="audit.payload_digest">
            请求体 SHA-256（payload_digest） <span class="hash">{{ audit.payload_digest }}</span>
          </p>
          <dl>
            <dt>需求</dt>
            <dd>{{ audit.payload_manifest.requirement?.length ?? 0 }} 项</dd>
            <dt>反馈</dt>
            <dd>{{ audit.payload_manifest.feedback?.length ?? 0 }} 项</dd>
            <dt>源码</dt>
            <dd>
              <span v-for="source in audit.payload_manifest.source || []" :key="source.path" class="mono">
                {{ source.path }} ({{ source.sha256 }})<br />
              </span>
              <span v-if="!audit.payload_manifest.source?.length">（无）</span>
            </dd>
            <dt>工具返回</dt>
            <dd>{{ audit.payload_manifest.tool_return?.length ?? 0 }} 项（候选 C 无工具，恒为空）</dd>
          </dl>
        </article>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  api,
  type Authorization,
  type Execution,
  type GenerationDetail,
  type SendAudit,
  type SnapshotSummary,
  type Verification,
} from '../api'
import { describeError } from '../api/errors'
import { runtime } from '../state/session'
import UsageCost from './UsageCost.vue'

const props = defineProps<{
  taskId: number
  authorizations: Authorization[]
  requirementContent: string
  initialExecutionId?: number
}>()
const emit = defineEmits<{
  executionSelected: [executionId: number]
  finished: []
}>()

const TERMINAL = new Set(['completed', 'failed', 'timeout', 'cancelled', 'late_result_discarded'])

const detail = ref<GenerationDetail | null>(null)
const snapshot = ref<SnapshotSummary | null>(null)
const error = ref('')
const notice = ref('')
const feedbackText = ref('')
const starting = ref(false)
const cancelling = ref(false)
const auditBusy = ref(false)
const audits = ref<SendAudit[]>([])
let timer: ReturnType<typeof setTimeout> | null = null

const activeAuthorization = computed(() => {
  return props.authorizations.find((auth) => auth.status === 'approved') || null
})

const isRunning = computed(() => {
  const status = detail.value?.execution.status
  return !!status && !TERMINAL.has(status)
})

const startDisabled = computed(() => startDisabledReason.value !== '')
const startDisabledReason = computed(() => {
  if (!props.requirementContent) return '尚无正式需求版本；先保存需求。'
  if (isRunning.value) return '已有运行中的生成；结束后可重试（重试使用新的执行标识）。'
  if (!activeAuthorization.value) return '没有有效的出站授权；请先创建授权（撤销/过期均不可用）。'
  if (runtime.testing) return ''
  if (!runtime.realAiEnabled) return '真实 AI 未启用（fail-closed）；生产模式默认禁止真实发送。'
  return ''
})

const statusClass = computed(() => {
  const status = detail.value?.execution.status
  if (status === 'completed') return 'ok'
  if (status === 'failed' || status === 'timeout') return 'bad'
  if (status === 'cancelled') return 'warn'
  return ''
})

const cancelLabel = computed(() => {
  const value = detail.value?.execution.cancel_outcome
  if (!value) return '—'
  if (value === 'cancelled') return 'cancelled：发送前拦截，未发送任何数据'
  if (value === 'not_cancelled') return 'not_cancelled：请求已发出，无法撤回已发送数据'
  if (value === 'already_finished') return 'already_finished：执行已结束'
  return value
})

const failureLabel = computed(() => {
  const reason = detail.value?.execution.failure_reason
  if (!reason) return '—'
  if (reason === 'restart_incomplete') return 'restart_incomplete：服务重启导致中断，证据不足，未判定 verified'
  if (reason === 'timeout') return 'timeout：适配器超时，未生成方案'
  return reason
})

onMounted(async () => {
  if (props.initialExecutionId) {
    await load(props.initialExecutionId)
  }
})

onBeforeUnmount(stopPolling)

watch(
  () => props.initialExecutionId,
  async (value) => {
    if (value && value !== detail.value?.execution.id) await load(value)
  },
)

function stopPolling(): void {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function schedule(): void {
  stopPolling()
  timer = setTimeout(async () => {
    if (detail.value) await load(detail.value.execution.id, false)
  }, 1000)
}

async function load(executionId: number, announce = true): Promise<void> {
  try {
    const result = await api.getGeneration(executionId)
    detail.value = result
    if (announce) error.value = ''
    if (TERMINAL.has(result.execution.status)) {
      stopPolling()
      emit('finished')
    } else {
      schedule()
    }
  } catch (err) {
    stopPolling()
    error.value = describeError(err)
  }
}

async function start(): Promise<void> {
  const auth = activeAuthorization.value
  if (!auth) return
  starting.value = true
  error.value = ''
  notice.value = ''
  audits.value = []
  try {
    const feedback = feedbackText.value.split('\n').map((line) => line.trim()).filter(Boolean)
    // 先取预览摘要并在请求中回传：真实发送必须与用户看到的范围/内容一致。
    const preview = await api.previewGeneration(props.taskId, auth.id, feedback)
    const result = await api.startGeneration(
      props.taskId,
      auth.id,
      feedback,
      preview.request_digest,
    )
    snapshot.value = result.snapshot
    detail.value = null
    emit('executionSelected', result.execution_id)
    await load(result.execution_id)
  } catch (err) {
    error.value = describeError(err)
  } finally {
    starting.value = false
  }
}

async function cancel(): Promise<void> {
  if (!detail.value) return
  cancelling.value = true
  error.value = ''
  try {
    const result = await api.cancelGeneration(detail.value.execution.id)
    if (result.outcome === 'already_finished') {
      notice.value = result.note
    } else {
      notice.value = `已受理取消请求；${result.note}。最终结果由工作线程写入（cancelled / not_cancelled）。`
    }
    await load(detail.value.execution.id, false)
  } catch (err) {
    error.value = describeError(err)
  } finally {
    cancelling.value = false
  }
}

async function loadAudit(): Promise<void> {
  if (!detail.value) return
  auditBusy.value = true
  error.value = ''
  try {
    const result = await api.sendAudit(detail.value.execution.id)
    audits.value = result.audits
  } catch (err) {
    error.value = describeError(err)
  } finally {
    auditBusy.value = false
  }
}

// 供核验栏使用：暴露当前执行的核验状态（若已有提案，父组件也能从其映射读取）。
defineExpose({
  currentVerification: computed<Verification | null>(() => detail.value?.verification ?? null),
  currentExecution: computed<Execution | null>(() => detail.value?.execution ?? null),
})
</script>