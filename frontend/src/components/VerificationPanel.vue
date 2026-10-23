<template>
  <div class="panel">
    <h3>核验状态（按方案版本）</h3>
    <p class="muted">
      核验为独立判定，不等同于审批；重启中断、超时或证据不足一律不判 verified。
    </p>
    <ul class="verification-list">
      <li v-for="proposal in orderedProposals" :key="proposal.id">
        <div class="row spread">
          <strong>v{{ proposal.seq }}</strong>
          <span :class="['chip', verificationClass(proposal)]">
            {{ verificationOf(proposal)?.status || '无记录' }}
          </span>
        </div>
        <p class="muted">
          execution={{ proposal.execution_id }} ·
          sufficient={{ verificationOf(proposal)?.evidence_sufficiency?.sufficient ?? '未知' }}
        </p>
        <p v-if="verificationOf(proposal)?.coverage_note" class="muted">
          {{ verificationOf(proposal)?.coverage_note }}
        </p>
      </li>
      <li v-if="orderedProposals.length === 0" class="muted">暂无核验对象。</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Proposal, Verification } from '../api'

const props = defineProps<{
  proposals: Proposal[]
  verifications: Record<number, Verification | null>
}>()

const orderedProposals = computed(() => [...props.proposals].sort((a, b) => b.seq - a.seq))

function verificationOf(proposal: Proposal): Verification | null {
  return props.verifications[proposal.id] ?? null
}

function verificationClass(proposal: Proposal): string {
  const status = verificationOf(proposal)?.status
  if (status === 'verified') return 'ok'
  if (status === 'unconfirmed') return 'warn'
  return ''
}
</script>