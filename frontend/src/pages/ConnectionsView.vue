<script setup>
// 本页 API：API-02（列表/筛选/分页）、API-03（创建）、API-04（更新）、API-05（测试，幂等豁免）。
// 权限：查看全员；新建/编辑/测试仅 Maker（Spec 2.3）。密钥仅状态展示，不落地前端。
// 请求体严格按契约 API-03/API-04；响应不返回 host/username/secret_ref 明文。
import { ref, computed, onMounted } from 'vue'
import { apiConnections } from '@/api/connections'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import SecretStateBadge from '@/components/SecretStateBadge.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import DonutChart from '@/components/DonutChart.vue'
import { formatIso } from '@/utils/time'

const project = useProjectStore()
const { can } = usePermission()
const notice = useNoticeStore()

const loading = ref(true)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const items = ref([])
const total = ref(0)

const filters = ref({ type: '', env: '', status: '' })
const page = ref(1)
const pageSize = 10

async function load() {
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  try {
    const res = await apiConnections.list(project.state.projectId, { ...filters.value, page: page.value, page_size: pageSize })
    // 契约 API-02 的 data 直接是分页对象。
    const data = res.data || { items: [], total: 0 }
    items.value = data.items
    total.value = data.total
  } catch (e) {
    if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  } finally {
    loading.value = false
  }
}

onMounted(load)

function applyFilters() {
  page.value = 1
  load()
}

const filtered = computed(() => Object.values(filters.value).some(Boolean))

// ---- 创建 / 编辑抽屉 ----
const DB_TYPES = ['mysql', 'doris', 'postgresql', 'clickhouse', 'oracle']
const drawerOpen = ref(false)
const editing = ref(null)
const emptyForm = () => ({
  name: '',
  type: 'mysql',
  env: 'test',
  host: '',
  port: 3306,
  database: '',
  username: '',
  secret_ref: '',
  readonly: true,
})
const form = ref(emptyForm())
const submitting = ref(false)
const formError = ref(null)

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  formError.value = null
  drawerOpen.value = true
}

function openEdit(conn) {
  editing.value = conn
  form.value = { ...emptyForm(), name: conn.name, type: conn.type, env: conn.env }
  formError.value = null
  drawerOpen.value = true
}

function optional(value) {
  const text = String(value ?? '').trim()
  return text === '' ? undefined : text
}

async function submitForm() {
  submitting.value = true
  formError.value = null
  try {
    if (editing.value) {
      // API-04：类型创建后不可变更；只提交页面可确认的名称与环境。
      await apiConnections.update(editing.value.id, {
        name: optional(form.value.name),
        env: form.value.env,
      })
      notice.push({ kind: 'success', text: `连接 ${form.value.name} 已更新（API-04）` })
    } else {
      // API-03：不接收密码字段，仅接收 Secret 引用。
      const body = {
        name: form.value.name,
        type: form.value.type,
        env: form.value.env,
        host: optional(form.value.host),
        port: Number(form.value.port) || undefined,
        database: optional(form.value.database),
        username: optional(form.value.username),
        secret_ref: optional(form.value.secret_ref),
        readonly: Boolean(form.value.readonly),
      }
      Object.keys(body).forEach((k) => body[k] === undefined && delete body[k])
      const res = await apiConnections.create(body)
      notice.push({ kind: 'success', text: `连接已创建：${res.data.id}（API-03）` })
    }
    drawerOpen.value = false
    load()
  } catch (e) {
    formError.value = e
  } finally {
    submitting.value = false
  }
}

function fieldError(field) {
  return formError.value?.details?.fields?.[field] || null
}

// ---- 连接测试（API-05，幂等豁免；仅 Maker） ----
const testingId = ref(null)

async function testConnection(conn) {
  testingId.value = conn.id
  try {
    const res = await apiConnections.test(conn.id)
    if (res.data?.success === true) {
      notice.push({ kind: 'success', text: `连接 ${conn.name} 测试通过（${res.data.latency_ms}ms）` })
    } else {
      notice.push({ kind: 'error', text: `连接 ${conn.name} 测试失败：${res.data?.error_code || '未知原因'}` })
    }
    load()
  } catch (e) {
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    testingId.value = null
  }
}

const typeDist = computed(() => {
  const m = {}
  items.value.forEach((c) => {
    m[c.type] = (m[c.type] || 0) + 1
  })
  return Object.entries(m).map(([name, count]) => ({ name, count }))
})
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">连接管理</h2>
      <MockBadge />
      <span class="spacer" style="flex: 1"></span>
      <button v-if="can('connection.manage')" class="btn primary" @click="openCreate">+ 新建连接</button>
    </div>

    <PermissionBar action="connection.manage" />

    <div class="tip-bar warn">
      密钥说明：前端仅展示“已配置/未配置”状态；Secret 由服务端密钥服务托管，绝不明文回显、不写日志、不进 localStorage（Spec 12.3）。
    </div>

    <div class="card">
      <div class="flex gap-8 wrap items-center" style="margin-bottom: 12px">
        <select v-model="filters.type" style="width: 150px">
          <option value="">全部类型</option>
          <option v-for="t in ['mysql', 'doris', 'postgresql', 'clickhouse', 'oracle', 'minio', 'rest_api']" :key="t" :value="t">{{ t }}</option>
        </select>
        <select v-model="filters.env" style="width: 120px">
          <option value="">全部环境</option>
          <option>prod</option>
          <option>preprod</option>
          <option>test</option>
        </select>
        <select v-model="filters.status" style="width: 120px">
          <option value="">全部状态</option>
          <option value="active">已启用</option>
          <option value="inactive">已停用</option>
        </select>
        <button class="btn" @click="applyFilters">筛选</button>
        <button v-if="filtered" class="btn ghost" @click="filters = { type: '', env: '', status: '' }; applyFilters()">清空</button>
      </div>

      <AppState v-if="loading" state="loading" />
      <AppState v-else-if="forbidden" state="forbidden" :error="error" />
      <AppState v-else-if="failed" state="error" :error="error" :retry="load" />
      <AppState v-else-if="!items.length && filtered" state="filtered-empty" :retry="() => { filters = { type: '', env: '', status: '' }; applyFilters() }" />
      <AppState v-else-if="!items.length" state="empty" />

      <template v-else>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>名称</th><th>类型</th><th>环境</th><th>源/目标</th><th>主机（脱敏）</th><th>密钥</th><th>状态</th><th>最近测试</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in items" :key="c.id">
                <td class="mono">{{ c.name }}</td>
                <td class="mono">{{ c.type }}</td>
                <td>{{ c.env }}</td>
                <td>{{ c.source_target === 'source' ? '源端' : c.source_target === 'target' ? '目标端' : c.source_target }}</td>
                <td class="mono dim">{{ c.host_masked }}</td>
                <td><SecretStateBadge :state="c.secret_state" /></td>
                <td><StatusBadge :status="c.status" /></td>
                <td class="dim">{{ formatIso(c.last_tested_at) }}</td>
                <td>
                  <div class="flex gap-8">
                    <button v-if="can('connection.test')" class="btn sm" :disabled="testingId === c.id" @click="testConnection(c)">
                      {{ testingId === c.id ? '测试中…' : '测试' }}
                    </button>
                    <button v-if="can('connection.manage')" class="btn sm ghost" @click="openEdit(c)">编辑</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex items-center gap-8 mt-8">
          <span class="faint">共 {{ total }} 条</span>
          <span class="spacer" style="flex: 1"></span>
          <button class="btn sm" :disabled="page <= 1" @click="page--; load()">上一页</button>
          <span class="dim">{{ page }}</span>
          <button class="btn sm" :disabled="page * pageSize >= total" @click="page++; load()">下一页</button>
        </div>
      </template>
    </div>

    <div class="card" v-if="!loading && !failed && !forbidden && typeDist.length">
      <div class="card-title">类型覆盖（当前筛选内）</div>
      <DonutChart :items="typeDist" :size="130" />
    </div>

    <!-- 创建 / 编辑抽屉（仅 Maker） -->
    <div v-if="drawerOpen" class="drawer-mask" @click.self="drawerOpen = false">
      <div class="drawer">
        <h3 class="d-title">{{ editing ? `编辑连接 ${editing.name}` : '新建连接' }}</h3>
        <div class="form-grid">
          <div class="form-field">
            <label>连接名 <span class="req">*</span></label>
            <input v-model="form.name" type="text" placeholder="如 orders_mysql" :disabled="submitting" />
            <div v-if="fieldError('name')" class="field-err">{{ fieldError('name') }}</div>
          </div>
          <div class="form-field">
            <label>类型 <span class="req">*</span></label>
            <select v-model="form.type" :disabled="submitting || Boolean(editing)">
              <option v-for="t in DB_TYPES" :key="t" :value="t">{{ t }}</option>
            </select>
            <div v-if="fieldError('type')" class="field-err">{{ fieldError('type') }}</div>
            <div v-if="editing" class="form-hint">类型创建后不可变更（CONN-422）</div>
          </div>
          <div class="form-field">
            <label>环境</label>
            <select v-model="form.env" :disabled="submitting">
              <option value="test">test</option>
              <option value="preprod">preprod</option>
              <option value="prod">prod</option>
            </select>
          </div>
          <template v-if="!editing">
            <div class="form-field">
              <label>主机 <span class="req">*</span></label>
              <input v-model="form.host" type="text" placeholder="主机名或 IP（不得含账号密码）" :disabled="submitting" />
              <div v-if="fieldError('host')" class="field-err">{{ fieldError('host') }}</div>
            </div>
            <div class="form-field">
              <label>端口 <span class="req">*</span></label>
              <input v-model="form.port" type="number" min="1" max="65535" :disabled="submitting" />
              <div v-if="fieldError('port')" class="field-err">{{ fieldError('port') }}</div>
            </div>
            <div class="form-field">
              <label>数据库 <span class="req">*</span></label>
              <input v-model="form.database" type="text" placeholder="如 orders" :disabled="submitting" />
              <div v-if="fieldError('database')" class="field-err">{{ fieldError('database') }}</div>
            </div>
            <div class="form-field">
              <label>用户名</label>
              <input v-model="form.username" type="text" placeholder="只读账号" :disabled="submitting" />
            </div>
            <div class="form-field">
              <label>Secret 引用</label>
              <input v-model="form.secret_ref" type="text" placeholder="vault://...（仅引用，不输入密钥）" :disabled="submitting" />
              <div v-if="fieldError('secret_ref')" class="field-err">{{ fieldError('secret_ref') }}</div>
            </div>
            <div class="form-field">
              <label>只读连接</label>
              <label class="dim"><input v-model="form.readonly" type="checkbox" :disabled="submitting" /> readonly=true</label>
            </div>
          </template>
        </div>
        <div v-if="formError" class="field-err mt-8">{{ formError.friendly() }}<template v-if="formError.errorCode">（{{ formError.errorCode }}）</template></div>
        <div class="btn-row mt-16" style="justify-content: flex-end">
          <button class="btn" :disabled="submitting" @click="drawerOpen = false">取消</button>
          <button class="btn primary" :disabled="submitting" @click="submitForm">{{ submitting ? '提交中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
