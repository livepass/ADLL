<template>
  <div class="panel">
    <h3>审批历史与有效性</h3>
    <p class="muted">
      审批事件不可变；有效性为独立实时判定（需求版本、基准、repo、方案内容哈希任一变化即失效），
      旧批准不被新版本继承。
    </p>
    <article v-for="event in approvals" :key="event.id" class="approval">
      <header class="row spread">
        <strong>#{{ event.id }} · {{ event.decision }}</strong>
        <span :class="['chip', event.effective ? 'ok' : 'muted-chip']">
          {{ event.effective ? '当前有效' : '已失效/非批准' }}
        </span>
      </header>
      <dl>
        <dt>proposal_version_id</dt>
        <dd>{{ event.proposal_version_id }}</dd>
        <dt>requirement_version_id</dt>
        <dd>{{ event.requirement_version_id }}</dd>
        <dt>repo_identity</dt>
        <dd class="mono">{{ event.repo_identity }}</dd>
        <dt>commit_sha（完整）</dt>
        <dd class="hash">{{ event.commit_sha }}</dd>
        <dt>proposal_content_hash（完整）</dt>
        <dd class="hash">{{ event.proposal_content_hash }}</dd>
        <dt>actor_role</dt>
        <dd>{{ event.actor_role }}</dd>
        <dt>理由</dt>
        <dd>{{ event.reason || '—' }}</dd>
        <dt>时间</dt>
        <dd>{{ event.created_at }}</dd>
      </dl>
    </article>
    <p v-if="approvals.length === 0" class="muted">暂无审批事件。</p>
  </div>
</template>

<script setup lang="ts">
import type { ApprovalEvent } from '../api'

defineProps<{ approvals: ApprovalEvent[] }>()
</script>