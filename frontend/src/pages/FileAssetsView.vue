<script setup>
// 本页 API：API-07（上传文件资产，multipart）；缺失接口 P-19 files.list（列表/解析状态）。
// 上传限 Maker（Spec 2.3）。预览一律掩码（Spec 12.3）；解析失败仅展示脱敏原因。
// API-07 表单字段按契约：file、format、source、project_id（对象存储时另加 object_storage_path）。
import { ref, computed, onMounted } from 'vue'
import { apiFiles } from '@/api/files'
import { missingApi } from '@/api/missing'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import MaskChip from '@/components/MaskChip.vue'
import { formatBytes, formatIso } from '@/utils/time'

const project = useProjectStore()
const { can } = usePermission()
const notice = useNoticeStore()

const loading = ref(true)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const items = ref([])
const listPending = ref(false)

async function load() {
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  listPending.value = false
  try {
    const res = await missingApi.fileAssetsList()
    items.value = res.data?.items || []
  } catch (e) {
    items.value = []
    if (e.isContractPending()) listPending.value = true
    else if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---- 上传（API-07） ----
const dragging = ref(false)
const uploading = ref(false)
const uploadError = ref(null)
const previewId = ref(null)

function formatOf(fileName) {
  const ext = String(fileName).split('.').pop()?.toLowerCase()
  if (ext === 'xlsx' || ext === 'xls') return 'excel'
  if (['csv', 'json', 'parquet'].includes(ext)) return ext
  return null
}

async function uploadFile(file) {
  uploading.value = true
  uploadError.value = null
  try {
    const format = formatOf(file.name)
    if (!format) throw new Error('仅支持 csv / excel / json / parquet')
    const fd = new FormData()
    fd.append('file', file)
    fd.append('project_id', project.state.projectId)
    fd.append('format', format)
    fd.append('source', 'local')
    const res = await apiFiles.upload(fd)
    notice.push({ kind: 'success', text: `文件资产已受理：${res.data.id}（API-07）` })
    await load()
  } catch (e) {
    uploadError.value = e
    notice.push({ kind: 'error', text: e.friendly?.() || e.message, errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    uploading.value = false
  }
}

function onDrop(event) {
  dragging.value = false
  if (!can('file.upload')) return
  const file = event.dataTransfer?.files?.[0]
  if (file) uploadFile(file)
}

function onPick(event) {
  const file = event.target.files?.[0]
  if (file) uploadFile(file)
}

const preview = computed(() => items.value.find((f) => f.id === previewId.value) || null)

const statusOf = (s) => ({ parsed: 'parsed', parse_failed: 'parse_failed', parsing: 'parsing' }[s] || s)
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">文件资产</h2>
      <MockBadge />
    </div>

    <PermissionBar action="file.upload" />

    <div
      v-if="can('file.upload')"
      class="card"
      :style="{ borderStyle: dragging ? 'dashed' : 'solid', borderColor: dragging ? 'var(--accent)' : undefined, textAlign: 'center' }"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <div v-if="uploading" class="state-box"><div class="spinner"></div><div>上传解析中…</div></div>
      <template v-else>
        <div class="dim">拖拽文件到此处，或点击选择（csv / excel / json / parquet）</div>
        <button class="btn primary mt-8" @click="$refs.fileInput.click()">选择文件</button>
        <input ref="fileInput" type="file" accept=".csv,.xlsx,.xls,.json,.parquet" style="display: none" @change="onPick" />
        <div v-if="uploadError" class="field-err mt-8">
          {{ uploadError.friendly?.() || uploadError.message }}
          <template v-if="uploadError.errorCode">（{{ uploadError.errorCode }}）</template>
        </div>
      </template>
    </div>

    <div class="card">
      <div class="card-title">文件列表</div>
      <AppState v-if="loading" state="loading" />
      <AppState v-else-if="forbidden" state="forbidden" :error="error" />
      <AppState v-else-if="failed" state="error" :error="error" :retry="load" />
      <AppState v-else-if="listPending" state="empty" title="文件资产列表接口待确认" text="缺少 files.list（Spec P-19）；上传动作仍可通过 API-07 发起，不展示合成列表。" />
      <AppState v-else-if="!items.length" state="empty" text="暂无文件资产" />
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>文件名</th><th>大小</th><th>格式</th><th>来源</th><th>状态</th><th>上传时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="f in items" :key="f.id">
              <td class="mono">{{ f.file_name }}</td>
              <td class="dim">{{ formatBytes(f.file_size) }}</td>
              <td class="mono">{{ f.file_format }}</td>
              <td>{{ f.source === 'local' ? '本地上传' : '对象存储' }}</td>
              <td><StatusBadge :status="statusOf(f.status)" /></td>
              <td class="dim">{{ formatIso(f.created_at) }}</td>
              <td><button class="btn sm ghost" @click="previewId = previewId === f.id ? null : f.id">预览</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="preview" class="card">
      <div class="card-title">
        文件预览：{{ preview.file_name }}
        <span class="sub">头 N 行 + 推断字段（值均掩码）</span>
        <span class="right"><button class="btn sm ghost" @click="previewId = null">关闭</button></span>
      </div>

      <template v-if="preview.schema_json">
        <div class="form-hint mb-16">推断字段：</div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>字段</th><th>类型</th><th>置信度</th><th>脱敏</th></tr></thead>
            <tbody>
              <tr v-for="fd in preview.schema_json.fields" :key="fd.name">
                <td class="mono">{{ fd.name }}</td>
                <td class="mono dim">{{ fd.type }}</td>
                <td>{{ fd.confidence }}</td>
                <td><span class="badge" :class="fd.masked ? 'pending' : 'gray'">{{ fd.masked ? '需掩码' : '明文' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="form-hint mt-8 mb-16">数据预览（脱敏）：</div>
        <div class="table-wrap" v-if="preview.head_preview?.length">
          <table class="table">
            <thead><tr><th v-for="k in Object.keys(preview.head_preview[0])" :key="k">{{ k }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, i) in preview.head_preview" :key="i">
                <td v-for="k in Object.keys(preview.head_preview[0])" :key="k"><MaskChip :value="row[k]" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <AppState v-else state="empty" text="无预览行" />
      </template>

      <template v-else-if="preview.parse_error">
        <div class="tip-bar warn">
          解析失败（脱敏原因）：{{ preview.parse_error.error_code }} · {{ preview.parse_error.message }}
        </div>
      </template>
    </div>
  </div>
</template>
