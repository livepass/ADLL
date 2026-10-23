<template>
  <section v-if="task" class="stack">
    <header class="page-head">
      <div>
        <h2>#{{ task.id }} {{ task.title }}</h2>
        <p class="muted">
          任务状态={{ task.status }} · repository={{ task.repository_id }} ·
          baseline={{ task.baseline_id }} · 当前批准={{ task.current_approval_id ?? '无' }}
        </p>
      </div>
      <router-link to="/">← 返回工作台</router-link>
    </header>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="panel">
      <h3>需求版本（不可变）</h3>
      <p v-if="task.current_requirement_version" class="muted">
        当前 v{{ task.current_requirement_version.seq }} · content_hash
        <span class="hash">{{ task.current_requirement_version.content_hash }}</span>
      </p>
      <p v-else class="warning">尚未保存正式需求；草稿不会产生版本。</p>
      <textarea v-model="requirementDraft" rows="4" :disabled="savingRequirement"></textarea>
      <div class="row">
        <button
          type="button"
          :disabled="savingRequirement || !requirementDraft.trim()"
          @click="saveRequirement"
        >
          {{ savingRequirement ? '保存中…' : '保存为新的正式需求版本' }}
        </button>
        <span class="muted">保存新需求会使旧审批失效（不继承）；不自动生成方案。</span>
      </div>
      <p v-if="requirementNotice" class="notice">{{ requirementNotice }}</p>
    </div>

    <div class="columns">
      <div class="column">
        <h3 class="column-title">执行</h3>
        <AuthorizationPanel
          :task-id="task.id"
          :authorizations="authorizations"
          :requirement-content="currentRequirement"
          @changed="reload"
        />
        <GenerationPanel
          :task-id="task.id"
          :authorizations="authorizations"
          :requirement-content="currentRequirement"
          :initial-execution-id="executionId"
          @execution-selected="selectExecution"
          @finished="reload"
        />
      </div>

      <div class="column">
        <h3 class="column-title">核验</h3>
        <VerificationPanel :proposals="proposals" :verifications="verifications" />
      </div>

      <div class="column">
        <h3 class="column-title">审批</h3>
        <ProposalPanel
          :task="task"
          :proposals="proposals"
          :verifications="verifications"
          @changed="reload"
        />
        <ApprovalPanel :approvals="approvals" />
      </div>
    </div>
  </section>

  <section v-else class="panel">
    <p v-if="loading">加载中…</p>
    <p v-else class="error">{{ error || '任务不存在。' }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type ApprovalEvent,
  type Authorization,
  type Proposal,
  type Task,
  type Verification,
} from '../api'
import { describeError } from '../api/errors'
import ApprovalPanel from '../components/ApprovalPanel.vue'
import AuthorizationPanel from '../components/AuthorizationPanel.vue'
import GenerationPanel from '../components/GenerationPanel.vue'
import ProposalPanel from '../components/ProposalPanel.vue'
import VerificationPanel from '../components/VerificationPanel.vue'

const route = useRoute()
const router = useRouter()

const task = ref<Task | null>(null)
const proposals = ref<Proposal[]>([])
const approvals = ref<ApprovalEvent[]>([])
const authorizations = ref<Authorization[]>([])
const verifications = ref<Record<number, Verification | null>>({})
const loading = ref(true)
const error = ref('')
const requirementDraft = ref('')
const savingRequirement = ref(false)
const requirementNotice = ref('')

const taskId = computed(() => Number(route.params.id))
const executionId = computed(() => {
  const raw = route.query.execution
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
})
const currentRequirement = computed(() => task.value?.current_requirement_version?.content || '')

onMounted(reload)
watch(taskId, reload)

async function reload(): Promise<void> {
  if (!Number.isFinite(taskId.value) || taskId.value <= 0) {
    error.value = '任务 ID 无效。'
    loading.value = false
    return
  }
  try {
    const [taskResp, proposalResp, approvalResp, authResp] = await Promise.all([
      api.getTask(taskId.value),
      api.listProposals(taskId.value),
      api.listApprovals(taskId.value),
      api.listAuthorizations(taskId.value),
    ])
    task.value = taskResp.task
    proposals.value = proposalResp.proposals
    approvals.value = approvalResp.approvals
    authorizations.value = authResp.authorizations
    if (!savingRequirement.value) {
      requirementDraft.value = taskResp.task.current_requirement_version?.content || ''
    }
    error.value = ''
    await loadVerifications()
  } catch (err) {
    error.value = describeError(err)
  } finally {
    loading.value = false
  }
}

async function loadVerifications(): Promise<void> {
  const entries = await Promise.all(
    proposals.value.map(async (proposal) => {
      try {
        const detail = await api.getGeneration(proposal.execution_id)
        return [proposal.id, detail.verification] as const
      } catch {
        return [proposal.id, null] as const
      }
    }),
  )
  const map: Record<number, Verification | null> = {}
  for (const [proposalId, verification] of entries) {
    map[proposalId] = verification
  }
  verifications.value = map
}

async function saveRequirement(): Promise<void> {
  if (!task.value) return
  savingRequirement.value = true
  error.value = ''
  requirementNotice.value = ''
  try {
    const result = await api.saveRequirement(task.value.id, requirementDraft.value.trim())
    requirementNotice.value = `已保存需求 v${result.requirement_version.seq}；旧审批不再有效。`
    await reload()
  } catch (err) {
    error.value = describeError(err)
  } finally {
    savingRequirement.value = false
  }
}

async function selectExecution(id: number): Promise<void> {
  await router.replace({ query: { ...route.query, execution: String(id) } })
}
</script>