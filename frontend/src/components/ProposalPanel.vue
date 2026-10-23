<template>
  <div class="panel">
    <h3>方案版本与审批</h3>
    <p class="muted">
      批准基于显式版本号，服务端在单个事务内复核：当前版本、需求版本与基准匹配、最新核验
      verified 且证据充分；不满足返回 409，不写入批准事件。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <article v-for="proposal in orderedProposals" :key="proposal.id" class="proposal">
      <header class="row spread">
        <strong>v{{ proposal.seq }}</strong>
        <span v-if="isCurrent(proposal)" class="chip ok">当前版本</span>
        <span v-if="proposal.approval_effective" class="chip ok">已批准且有效</span>
        <span v-else-if="proposal.has_approved_event" class="chip warn">曾批准但已失效</span>
      </header>

      <pre class="proposal-content">{{ proposal.content }}</pre>
      <p class="muted">
        content_hash <span class="hash">{{ proposal.content_hash }}</span>
      </p>
      <p class="muted">
        requirement_version_id={{ proposal.requirement_version_id }} ·
        baseline_id={{ proposal.baseline_id }} · execution={{ proposal.execution_id }} ·
        {{ proposal.created_at }}
      </p>

      <div class="gate">
        <h4>批准前置（本地提示，最终以服务端事务复核为准）</h4>
        <ul>
          <li :class="gateClass(gate(proposal).isCurrent)">当前方案版本（max seq）</li>
          <li :class="gateClass(gate(proposal).requirementMatch)">需求版本与当前指针一致</li>
          <li :class="gateClass(gate(proposal).baselineMatch)">分析基准与当前任务一致</li>
          <li :class="gateClass(gate(proposal).verified)">最新核验 verified 且证据充分</li>
        </ul>
        <p v-if="verificationOf(proposal)" class="muted">
          核验状态={{ verificationOf(proposal)?.status }} ·
          sufficient={{ verificationOf(proposal)?.evidence_sufficiency?.sufficient ?? '未知' }}
          <template v-if="verificationOf(proposal)?.coverage_note">
            · {{ verificationOf(proposal)?.coverage_note }}
          </template>
        </p>
        <p v-else class="muted">尚无核验记录。</p>
      </div>

      <div class="row">
        <button
          type="button"
          :disabled="busy || !canApprove(proposal)"
          :title="approveTitle(proposal)"
          @click="approve(proposal)"
        >
          批准此版本
        </button>
        <button
          type="button"
          class="danger"
          :disabled="busy || proposal.approval_effective"
          @click="toggleReject(proposal.seq)"
        >
          驳回…
        </button>
        <button type="button" :disabled="busy" @click="toggleFeedback(proposal.seq)">
          提交意见…
        </button>
      </div>

      <div v-if="rejecting === proposal.seq" class="stack-tight">
        <textarea v-model="rejectReason" rows="2" placeholder="驳回理由（必填，记录到不可变事件）"></textarea>
        <button
          type="button"
          class="danger"
          :disabled="busy || !rejectReason.trim()"
          @click="reject(proposal)"
        >
          确认驳回
        </button>
      </div>

      <div v-if="feedbackFor === proposal.seq" class="stack-tight">
        <textarea v-model="feedbackText" rows="2" placeholder="意见内容（生成新版本需要真实 Adapter）"></textarea>
        <button type="button" :disabled="busy || !feedbackText.trim()" @click="submitFeedback(proposal)">
          提交意见
        </button>
      </div>
    </article>

    <p v-if="orderedProposals.length === 0" class="muted">暂无方案版本。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type Proposal, type Task, type Verification } from '../api'
import { describeError } from '../api/errors'

const props = defineProps<{
  task: Task
  proposals: Proposal[]
  verifications: Record<number, Verification | null>
}>()
const emit = defineEmits<{ changed: [] }>()

const busy = ref(false)
const error = ref('')
const notice = ref('')
const rejecting = ref<number | null>(null)
const rejectReason = ref('')
const feedbackFor = ref<number | null>(null)
const feedbackText = ref('')

const orderedProposals = computed(() =>
  [...props.proposals].sort((a, b) => b.seq - a.seq),
)
const maxSeq = computed(() => Math.max(0, ...props.proposals.map((p) => p.seq)))

function isCurrent(proposal: Proposal): boolean {
  return proposal.seq === maxSeq.value
}

function verificationOf(proposal: Proposal): Verification | null {
  return props.verifications[proposal.id] ?? null
}

interface Gate {
  isCurrent: boolean
  requirementMatch: boolean
  baselineMatch: boolean
  verified: boolean
}

function gate(proposal: Proposal): Gate {
  const verification = verificationOf(proposal)
  return {
    isCurrent: isCurrent(proposal),
    requirementMatch:
      props.task.current_requirement_version?.id === proposal.requirement_version_id,
    baselineMatch: props.task.baseline_id === proposal.baseline_id,
    verified:
      verification?.status === 'verified' &&
      verification?.evidence_sufficiency?.sufficient === true,
  }
}

function canApprove(proposal: Proposal): boolean {
  const result = gate(proposal)
  return (
    !proposal.approval_effective &&
    result.isCurrent &&
    result.requirementMatch &&
    result.baselineMatch &&
    result.verified
  )
}

function approveTitle(proposal: Proposal): string {
  if (proposal.approval_effective) return '已有有效批准'
  if (canApprove(proposal)) return '提交批准（服务端将再次复核）'
  return '前置未满足；服务端会返回 409 并拒绝写入'
}

function gateClass(ok: boolean): string {
  return ok ? 'gate-ok' : 'gate-missing'
}

function toggleReject(seq: number): void {
  rejecting.value = rejecting.value === seq ? null : seq
  rejectReason.value = ''
}

function toggleFeedback(seq: number): void {
  feedbackFor.value = feedbackFor.value === seq ? null : seq
  feedbackText.value = ''
}

async function approve(proposal: Proposal): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.approve(props.task.id, proposal.seq)
    notice.value = `已批准 v${proposal.seq}（事件 #${result.approval.id}）；有效性以服务端实时判定为准。`
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function reject(proposal: Proposal): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await api.reject(props.task.id, proposal.seq, rejectReason.value.trim())
    notice.value = `已驳回 v${proposal.seq}；任务回到可迭代状态。`
    rejecting.value = null
    rejectReason.value = ''
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}

async function submitFeedback(proposal: Proposal): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.feedback(props.task.id, proposal.seq, feedbackText.value.trim())
    notice.value = result.regeneration.available
      ? '意见已记录；已触发新版本生成。'
      : `意见已记录。需要新版本=${result.regeneration.required ? '是' : '否'}，但当前不可自动生成（${result.regeneration.reason || '不可用'}）；不会伪造新版本。`
    feedbackFor.value = null
    feedbackText.value = ''
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
  } finally {
    busy.value = false
  }
}
</script>