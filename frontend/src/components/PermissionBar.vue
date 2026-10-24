<script setup>
// 权限提示条：按 Spec 2.3 权限矩阵显示当前角色对该动作的只读/禁止/待确认说明。
// 前端隐藏不构成安全边界：所有写操作由服务端二次复核。
import { computed } from 'vue'
import { usePermission } from '@/composables/usePermission'

const props = defineProps({
  action: { type: String, required: true },
})

const { verdict, pending } = usePermission()

const v = computed(() => verdict(props.action))
const note = computed(() => {
  if (v.value === 'allow') return null
  if (pending(props.action)) return '权限矩阵待确认（Spec 2.3），当前按只读渲染'
  if (v.value === 'readonly') return '当前角色只读'
  return '当前角色禁止该操作'
})
</script>

<template>
  <div v-if="note" class="permission-bar">
    <span class="badge" :class="v === 'forbid' ? 'danger' : 'pending'">{{ v === 'forbid' ? '禁止' : v === 'readonly' ? '只读' : '待确认' }}</span>
    <span class="perm-note">{{ note }}</span>
  </div>
</template>
