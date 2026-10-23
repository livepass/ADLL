<template>
  <section class="outbound-preview">
    <p v-if="preview.testing" class="chip warn">
      Mock 合成模式：本次不发送源码、不调用外部 AI；数据由本地 Mock 生成。
    </p>

    <dl class="preview-meta">
      <dt>接收端点</dt>
      <dd class="mono">{{ preview.receiver }}</dd>
      <dt>模型</dt>
      <dd class="mono">{{ preview.model || '（未配置）' }}</dd>
      <dt>数据类型</dt>
      <dd>{{ preview.data_types.join('、') || '（无）' }}</dd>
      <dt>请求 SHA-256</dt>
      <dd class="hash">{{ preview.request_digest }}</dd>
      <dt>快照 SHA-256</dt>
      <dd class="hash">{{ preview.snapshot.digest }}</dd>
    </dl>

    <details class="part" open>
      <summary>待发送正文（与 HTTP 请求体逐字一致 · {{ preview.message.bytes }} B）</summary>
      <p class="muted">
        sha256 <span class="hash">{{ preview.message.sha256 }}</span> ·
        下方内容可滚动查看全文，不是哈希占位。
      </p>
      <pre class="wire">{{ preview.message.content }}</pre>
    </details>

    <details class="part">
      <summary>需求原文（{{ preview.requirement.bytes }} B）</summary>
      <pre class="wire">{{ preview.requirement.content }}</pre>
    </details>

    <details v-if="preview.feedback.length" class="part">
      <summary>反馈原文（{{ preview.feedback.length }} 条）</summary>
      <article v-for="(item, index) in preview.feedback" :key="index">
        <p class="muted">
          #{{ index + 1 }} · {{ item.bytes }} B · <span class="hash">{{ item.sha256 }}</span>
        </p>
        <pre class="wire">{{ item.content }}</pre>
      </article>
    </details>

    <details v-for="item in preview.source" :key="item.path" class="part">
      <summary>{{ item.path }}（{{ item.bytes }} B）</summary>
      <p class="muted">sha256 <span class="hash">{{ item.sha256 }}</span></p>
      <pre class="wire">{{ item.content }}</pre>
    </details>

    <p v-if="!preview.source.length" class="muted">本次不发送任何源码文件。</p>

    <p v-if="preview.snapshot.excluded.length" class="muted">
      已排除：
      {{ preview.snapshot.excluded.map((e) => `${e.path}（${e.reason}）`).join('、') }}
    </p>
    <p v-for="warning in preview.snapshot.warnings" :key="warning" class="warning">
      属性提示：{{ warning }}
    </p>
  </section>
</template>

<script setup lang="ts">
import type { PreviewResponse } from '../api'

defineProps<{ preview: PreviewResponse }>()
</script>

<style scoped>
.outbound-preview {
  border: 1px solid #e3e3e3;
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
  margin: 0.5rem 0;
}
.preview-meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.2rem 0.75rem;
  font-size: 0.85rem;
}
.preview-meta dt {
  color: #666;
}
.preview-meta dd {
  margin: 0;
  word-break: break-all;
}
.part {
  margin-top: 0.5rem;
  border-top: 1px dashed #e3e3e3;
  padding-top: 0.4rem;
}
.part summary {
  cursor: pointer;
  font-family: monospace;
  font-size: 0.88rem;
}
.wire {
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafafa;
  border: 1px solid #eee;
  border-radius: 4px;
  padding: 0.5rem;
  font-size: 0.82rem;
  margin: 0.35rem 0 0;
}
</style>
