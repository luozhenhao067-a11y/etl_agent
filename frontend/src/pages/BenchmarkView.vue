<script setup>
// 本页 API：API-18（触发 Benchmark 评测，仅 Checker 2）。
// 缺失接口 P-24 benchmark.history / benchmark.results / governance.*：
// 不聚合、不伪造评测历史或进化候选，只显示“待确认”空态。
// 评测数值不由前端计算或硬编码。
import { ref } from 'vue'
import { apiBenchmarks } from '@/api/benchmarks'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'

const { can } = usePermission()
const notice = useNoticeStore()

const triggerForm = ref({ suite_id: 'suite_demo_001', layer: 'L0', dataset_version: 'ds_demo_v1' })
const triggering = ref(false)
const triggerError = ref(null)

async function triggerBenchmark() {
  triggering.value = true
  triggerError.value = null
  try {
    const res = await apiBenchmarks.run(triggerForm.value)
    notice.push({ kind: 'success', text: `评测已启动：${res.data.benchmark_run_id}（API-18）` })
  } catch (e) {
    triggerError.value = e
  } finally {
    triggering.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">安全评测与进化</h2>
      <MockBadge />
    </div>

    <div class="grid cols-2">
      <div class="card">
        <div class="card-title">触发评测 <span class="sub">API-18 · 仅 Checker 2</span></div>
        <PermissionBar action="benchmark.trigger" />
        <div class="form-grid">
          <div class="form-field">
            <label>套件</label>
            <select v-model="triggerForm.suite_id" :disabled="!can('benchmark.trigger')">
              <option value="suite_demo_001">安全注入套件（演示）</option>
              <option value="suite_demo_002">字段推断套件（演示）</option>
            </select>
            <div class="form-hint">套件列表接口未定义 P-24；此处仅使用契约示例 ID。</div>
          </div>
          <div class="form-field">
            <label>评测层</label>
            <select v-model="triggerForm.layer" :disabled="!can('benchmark.trigger')">
              <option value="L0">L0 · 单元级</option>
              <option value="L1">L1 · 集成级</option>
              <option value="L2">L2 · 端到端</option>
            </select>
          </div>
          <div class="form-field">
            <label>数据集版本</label>
            <input v-model="triggerForm.dataset_version" type="text" :disabled="!can('benchmark.trigger')" />
          </div>
        </div>
        <div v-if="triggerError" class="field-err mt-8">
          {{ triggerError.friendly() }}（{{ triggerError.errorCode }}）
          <template v-if="triggerError.correlationId"> · {{ triggerError.correlationId }}</template>
        </div>
        <div class="btn-row mt-8">
          <button v-if="can('benchmark.trigger')" class="btn primary" :disabled="triggering" @click="triggerBenchmark">{{ triggering ? '触发中…' : '触发评测' }}</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">最近结果 <span class="sub">待确认 P-24</span></div>
        <AppState state="empty" title="评测结果接口待确认" text="benchmark.results 未定义（Spec P-24）；不展示合成指标。" />
      </div>
    </div>

    <div class="card">
      <div class="card-title">评测历史 <span class="sub">待确认 P-24 benchmark.history</span></div>
      <AppState state="empty" title="评测历史接口待确认" text="benchmark.history 未定义（Spec P-24）；不展示合成历史。" />
    </div>

    <div class="card">
      <div class="card-title">安全进化候选 <span class="sub">待确认 P-24 governance.*</span></div>
      <PermissionBar action="benchmark.govern" />
      <AppState state="empty" title="进化候选接口待确认" text="候选审查、灰度与停用接口未定义（Spec P-24）；前端不提供入口。" />
      <div class="tip-bar info mt-8">总停用开关（kill switch）状态：不可用 · 接口待确认 P-24</div>
    </div>
  </div>
</template>
