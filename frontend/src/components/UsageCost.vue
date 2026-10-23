<template>
  <div class="usage-cost">
    <div>
      <h4>用量（Token）</h4>
      <p v-if="usageAvailable">
        input_tokens={{ usage?.input_tokens ?? '—' }} · output_tokens={{ usage?.output_tokens ?? '—' }}
      </p>
      <p v-else class="muted">不可用（usage_basis={{ execution.usage_basis || 'unavailable' }}）</p>
    </div>
    <div>
      <h4>费用</h4>
      <template v-if="costBasis === 'actual'">
        <p v-if="cost?.amount != null">实际账单：{{ cost.amount }} {{ cost.currency || '' }}</p>
        <p v-else class="muted">实际账单不可用（basis=actual，金额未返回）</p>
      </template>
      <template v-else-if="costBasis === 'estimated'">
        <p v-if="cost?.amount != null">
          按费率估算（非账单）：{{ cost.amount }} {{ cost.currency || '' }}
        </p>
        <p v-else class="muted">估算不可用</p>
        <p v-if="cost?.method" class="muted">估算方法：{{ cost.method }}</p>
      </template>
      <p v-else class="muted">不可用（basis={{ costBasis || 'unknown' }}）；不显示金额，也不由用量推断。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Execution } from '../api'

const props = defineProps<{ execution: Execution }>()

const usageAvailable = computed(
  () => props.execution.usage != null && props.execution.usage_basis !== 'unavailable',
)
const usage = computed(() => props.execution.usage)
const cost = computed(() => props.execution.cost)
const costBasis = computed(() => props.execution.cost?.basis || 'unknown')
</script>