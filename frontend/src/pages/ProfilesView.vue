<script setup>
// 本页 API：API-06（发起元数据探查，仅源端）；缺失接口 P-19 profiles.results（探查结果读取）。
// 敏感样本一律掩码展示（Spec 12.3）；只读角色无“发起探查”入口（Spec 2.3）。
// API-06 请求体按契约：schemas、tables、sample_rows、readonly=true；Idempotency-Key 由适配层添加。
import { ref, computed, onMounted } from 'vue'
import { apiProfiles } from '@/api/profiles'
import { apiConnections } from '@/api/connections'
import { missingApi } from '@/api/missing'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import MaskChip from '@/components/MaskChip.vue'
import KpiStrip from '@/components/KpiStrip.vue'
import { formatIso } from '@/utils/time'

const project = useProjectStore()
const { can } = usePermission()
const notice = useNoticeStore()

const loading = ref(true)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const connections = ref([])
const selectedId = ref('')
const profile = ref(null)
const profilePending = ref(false)
const profiling = ref(false)

const profileForm = ref({ schemas: 'sales', tables: 'orders', sample_rows: 20 })

function splitList(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

async function loadConnections() {
  try {
    const res = await apiConnections.list(project.state.projectId, { page: 1, page_size: 100 })
    const all = res.data?.items || []
    connections.value = all.filter((c) => c.source_target === 'source')
    if (!selectedId.value && connections.value.length) selectedId.value = connections.value[0].id
  } catch (e) {
    if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  }
}

async function loadProfile() {
  if (!selectedId.value) {
    loading.value = false
    return
  }
  profilePending.value = false
  try {
    const res = await missingApi.profileResults(selectedId.value)
    profile.value = res.data
  } catch (e) {
    profile.value = null
    if (e.isContractPending()) {
      profilePending.value = true
    } else if (e.isForbidden()) {
      forbidden.value = true
      error.value = e
    } else {
      failed.value = true
      error.value = e
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadConnections()
  await loadProfile()
})

async function selectConnection() {
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  profile.value = null
  await loadProfile()
}

async function runProfile() {
  profiling.value = true
  try {
    const body = {
      schemas: splitList(profileForm.value.schemas),
      tables: splitList(profileForm.value.tables),
      sample_rows: Number(profileForm.value.sample_rows),
      readonly: true,
    }
    const res = await apiProfiles.run(selectedId.value, body)
    notice.push({ kind: 'success', text: `探查已完成：${res.data.profile_status}（API-06）` })
    await selectConnection()
  } catch (e) {
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    profiling.value = false
  }
}

const kpis = computed(() => {
  if (!profile.value) return []
  const tables = profile.value.tables || []
  const columns = profile.value.columns || []
  const samples = profile.value.masked_samples || []
  return [
    { label: '数据表', value: tables.length },
    { label: '字段数', value: columns.length },
    { label: '需掩码字段', value: columns.filter((c) => c.masked).length },
    { label: '抽样行数', value: samples.length, note: '采样仅为探查，非全量' },
  ]
})
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">元数据探查</h2>
      <MockBadge />
      <span class="spacer" style="flex: 1"></span>
      <select v-model="selectedId" style="min-width: 220px" @change="selectConnection">
        <option v-for="c in connections" :key="c.id" :value="c.id">{{ c.name }}（{{ c.type }}）</option>
      </select>
      <button v-if="can('metadata.profile')" class="btn primary" :disabled="profiling || !selectedId" @click="runProfile">
        {{ profiling ? '探查中…' : '发起探查' }}
      </button>
    </div>

    <PermissionBar action="metadata.profile" />

    <div v-if="can('metadata.profile')" class="card">
      <div class="card-title">探查范围 <span class="sub">API-06 请求参数</span></div>
      <div class="form-grid">
        <div class="form-field">
          <label>Schema（逗号分隔）</label>
          <input v-model="profileForm.schemas" type="text" :disabled="profiling" />
        </div>
        <div class="form-field">
          <label>表（逗号分隔）</label>
          <input v-model="profileForm.tables" type="text" :disabled="profiling" />
        </div>
        <div class="form-field">
          <label>抽样行数</label>
          <input v-model.number="profileForm.sample_rows" type="number" min="0" :disabled="profiling" />
        </div>
      </div>
      <div class="form-hint mt-8">readonly 固定为 true；抽样仅用于探查，不是全量读取。</div>
    </div>

    <AppState v-if="loading" state="loading" />
    <AppState v-else-if="forbidden" state="forbidden" :error="error" />
    <AppState v-else-if="failed" state="error" :error="error" :retry="selectConnection" />
    <AppState v-else-if="profilePending" state="empty" title="探查结果读取接口待确认" text="缺少 profiles.results（Spec P-19）；不展示合成数据。探查请求本身可通过上方按钮发起。" />
    <AppState v-else-if="profile && profile.profile_status === 'none'" state="empty" text="该连接尚无探查结果" />

    <template v-else-if="profile">
      <KpiStrip :items="kpis" />

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">
            表清单与分级
            <span class="right"><StatusBadge :status="profile.profile_status" /></span>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>表</th><th>数据分级</th><th>备注</th></tr></thead>
              <tbody>
                <tr v-for="t in profile.tables || []" :key="t.name">
                  <td class="mono">{{ t.name }}</td>
                  <td><span class="badge" :class="`risk-${String(t.classification || 'unknown').toLowerCase()}`">{{ t.classification || '—' }}</span></td>
                  <td class="dim">{{ t.note || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-title">字段清单（脱敏标注）</div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>字段</th><th>类型</th><th>主键</th><th>可空</th><th>脱敏</th><th>分级</th></tr></thead>
              <tbody>
                <tr v-for="col in profile.columns || []" :key="col.name">
                  <td class="mono">{{ col.name }}</td>
                  <td class="mono dim">{{ col.type }}</td>
                  <td>{{ col.pk ? '✓' : '—' }}</td>
                  <td>{{ col.nullable ? '是' : '否' }}</td>
                  <td><span class="badge" :class="col.masked ? 'pending' : 'gray'">{{ col.masked ? '需掩码' : '明文' }}</span></td>
                  <td><span class="badge" :class="`risk-${String(col.classification || 'unknown').toLowerCase()}`">{{ col.classification || '—' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          抽样样本（仅掩码值，Spec 12.3）
          <span class="sub">采样时间 {{ formatIso(profile.sampled_at) }}</span>
        </div>
        <div v-if="profile.masked_samples?.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr><th v-for="k in Object.keys(profile.masked_samples[0])" :key="k">{{ k }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in profile.masked_samples" :key="i">
                <td v-for="k in Object.keys(profile.masked_samples[0])" :key="k"><MaskChip :value="row[k]" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <AppState v-else state="empty" text="无样本" />
        <div class="form-hint mt-8">服务端返回的样本必须已脱敏；原始敏感值不落前端。</div>
      </div>
    </template>
  </div>
</template>
