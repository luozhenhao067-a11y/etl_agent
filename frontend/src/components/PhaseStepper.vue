<script setup>
// 三阶段状态条：prepare → approve → commit（Spec 6.10）。
// approve 阶段显示 n/2；rejected 时 approve 标红。
import { computed } from 'vue'

const props = defineProps({
  phase: { type: String, required: true }, // prepare|approve|commit|committed|rejected
  approvedCount: { type: Number, default: 0 },
  totalApprovals: { type: Number, default: 2 },
})

const steps = computed(() => {
  const { phase, approvedCount, totalApprovals } = props
  const seq = { prepare: 0, approve: 1, commit: 2, committed: 2, rejected: 1 }
  const at = seq[phase] ?? 0
  const list = [
    {
      key: 'prepare',
      label: '生成准备',
      sub: 'Preparation',
      state: at > 0 ? 'done' : 'active',
    },
    {
      key: 'approve',
      label: `审批 ${approvedCount}/${totalApprovals}`,
      sub: '双人独立审批',
      state: phase === 'rejected' ? 'failed' : at > 1 ? 'done' : at === 1 ? 'active' : 'todo',
    },
    {
      key: 'commit',
      label: '提交执行',
      sub: 'Ops Commit',
      state: phase === 'committed' ? 'done' : at > 2 ? 'done' : 'todo',
    },
  ]
  return list
})
</script>

<template>
  <div class="stepper">
    <template v-for="(s, i) in steps" :key="s.key">
      <div class="step" :class="s.state">
        <span class="node">{{ s.state === 'done' ? '✓' : s.state === 'failed' ? '✕' : i + 1 }}</span>
        <span>
          <span class="label">{{ s.label }}</span><br />
          <span class="sub">{{ s.sub }}</span>
        </span>
      </div>
      <span v-if="i < steps.length - 1" class="step-conn" :class="{ done: s.state === 'done' }"></span>
    </template>
  </div>
</template>
