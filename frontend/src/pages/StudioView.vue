<script setup>
// 本页 API：API-08（创建 Pipeline）、API-09（发起生成）、API-10（澄清回答）、
// API-11（读取设计）、API-12（提交 Preparation）；缺失接口 P-18 versions.*。
// 请求/响应严格按契约：API-09 {prompt, source_profile_ref, target_profile_ref, provider, thread_id}
// 与响应 interrupt；API-10 {answers, thread_id}；API-12 {schedule, budget, quality_contract_ref}。
// 缺失的版本列表/冻结接口只显示“待确认”，不以 mock 数据替代。
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiPipelines } from '@/api/pipelines'
import { apiGeneration } from '@/api/generation'
import { apiDesign } from '@/api/design'
import { apiPreparations } from '@/api/preparations'
import { missingApi } from '@/api/missing'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import { newThreadId } from '@/utils/idem'
import AppState from '@/components/AppState.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import HoconCodeBlock from '@/components/HoconCodeBlock.vue'
import DagCanvas from '@/components/DagCanvas.vue'
import DiffViewer from '@/components/DiffViewer.vue'
import GateChecklist from '@/components/GateChecklist.vue'

const route = useRoute()
const router = useRouter()
const project = useProjectStore()
const { can } = usePermission()
const notice = useNoticeStore()

const versionId = computed(() => String(route.params.versionId || 'ver_demo_002'))

const loading = ref(true)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const versions = ref([])
const versionsPending = ref(false)
const design = ref(null)
const designNotReady = ref(false)
const designError = ref(null)

async function loadMeta() {
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  versionsPending.value = false
  try {
    const vres = await missingApi.versionList()
    versions.value = vres.data?.items || []
  } catch (e) {
    versions.value = []
    if (e.isContractPending()) versionsPending.value = true
    else if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  }
  if (!forbidden.value && !failed.value) await loadDesign()
  loading.value = false
}

onMounted(loadMeta)
watch(versionId, loadMeta)

const currentVersion = computed(() => versions.value.find((v) => v.version_id === versionId.value) || null)

function switchVersion(event) {
  router.push(`/studio/${event.target.value}`)
}

// ---- API-09 发起生成 ----
const generationForm = ref({
  prompt: '',
  source_profile_ref: 'profile_demo_src_001',
  target_profile_ref: 'profile_demo_dst_001',
  provider: 'deepseek',
})
const generating = ref(false)
const generateError = ref(null)
const agentRunId = ref(null)
const threadId = ref(null)
const interrupted = ref(false)
const question = ref(null)
const answers = ref({})

function applyInterrupt(nextQuestion) {
  question.value = nextQuestion || null
  interrupted.value = Boolean(nextQuestion)
  answers.value = {}
  ;(nextQuestion?.fields || []).forEach((f) => {
    if (f.type === 'boolean') answers.value[f.name] = false
    else if (f.type === 'enum') answers.value[f.name] = f.options?.[0] ?? ''
    else answers.value[f.name] = ''
  })
}

async function startGenerate() {
  generating.value = true
  generateError.value = null
  try {
    const thread = newThreadId()
    const res = await apiGeneration.generate(versionId.value, { ...generationForm.value, thread_id: thread })
    agentRunId.value = res.data.agent_run_id
    threadId.value = res.data.thread_id
    applyInterrupt(res.data.interrupt)
    notice.push({ kind: 'success', text: `生成已启动：${res.data.agent_run_id}（API-09）` })
    if (res.data.status === 'completed') await loadDesign()
  } catch (e) {
    generateError.value = e
  } finally {
    generating.value = false
  }
}

// ---- API-10 澄清回答 ----
const answering = ref(false)
const answerError = ref(null)

async function submitAnswers() {
  answering.value = true
  answerError.value = null
  try {
    const res = await apiGeneration.answer(agentRunId.value, {
      answers: answers.value,
      thread_id: threadId.value,
    })
    notice.push({ kind: 'success', text: `回答已提交：${res.data.status}（API-10）` })
    if (res.data.design_ready) {
      interrupted.value = false
      question.value = null
      await loadDesign()
    }
  } catch (e) {
    answerError.value = e
  } finally {
    answering.value = false
  }
}

// ---- API-08 创建 Pipeline ----
const pipelineForm = ref({ name: '', code: '', description: '' })
const pipelineSubmitting = ref(false)
const pipelineError = ref(null)
const showPipelineForm = ref(false)

async function createPipeline() {
  pipelineSubmitting.value = true
  pipelineError.value = null
  try {
    const body = {
      project_id: project.state.projectId,
      name: pipelineForm.value.name,
      code: pipelineForm.value.code,
      description: pipelineForm.value.description || undefined,
    }
    const res = await apiPipelines.create(body)
    notice.push({ kind: 'success', text: `Pipeline 已创建：${res.data.pipeline_id}（API-08）` })
    showPipelineForm.value = false
    pipelineForm.value = { name: '', code: '', description: '' }
    await loadMeta()
  } catch (e) {
    pipelineError.value = e
  } finally {
    pipelineSubmitting.value = false
  }
}

// ---- 设计区 ----
const designTabs = ref('plan')
const gateItems = computed(() => {
  const g = design.value?.gate_result
  if (!g) return []
  return [
    { key: 'syntax', status: g.syntax, note: g.syntax === 'passed' ? 'HOCON 语法通过' : '' },
    { key: 'schema', status: g.schema, note: g.schema === 'passed' ? '结构映射通过' : '' },
    { key: 'masking', status: g.masking, note: g.masking === 'passed' ? '脱敏规则通过' : '' },
    { key: 'budget', status: g.budget, note: g.budget === 'passed' ? '预算预检通过' : '' },
  ]
})
const gateAllPassed = computed(() => gateItems.value.length === 4 && gateItems.value.every((x) => x.status === 'passed'))
const maskTargets = computed(() => Object.entries(design.value?.masking || {}).map(([f, v]) => ({ field: f, before: v.before, after: v.after })))

async function loadDesign() {
  designNotReady.value = false
  designError.value = null
  try {
    const res = await apiDesign.get(versionId.value)
    design.value = res.data
  } catch (e) {
    design.value = null
    if (e.httpStatus === 409) {
      designNotReady.value = true
    } else if (e.isForbidden()) {
      forbidden.value = true
      error.value = e
    } else {
      designError.value = e
    }
  }
}

// ---- API-12 提交 Preparation（Maker） ----
const prepareForm = ref({
  schedule_mode: 'manual',
  max_input_rows: 100000,
  max_duration_seconds: 600,
  quality_contract_ref: 'qc_demo_001',
})
const preparing = ref(false)
const prepareError = ref(null)

async function submitPrepare() {
  preparing.value = true
  prepareError.value = null
  try {
    const body = {
      schedule: { mode: prepareForm.value.schedule_mode },
      budget: {
        max_input_rows: Number(prepareForm.value.max_input_rows),
        max_duration_seconds: Number(prepareForm.value.max_duration_seconds),
      },
      quality_contract_ref: prepareForm.value.quality_contract_ref,
    }
    const res = await apiPreparations.prepare(versionId.value, body)
    notice.push({ kind: 'success', text: `准备单已生成：${res.data.preparation_id}（API-12）` })
    router.push('/runs/preparations')
  } catch (e) {
    prepareError.value = e
  } finally {
    preparing.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">生成 Studio</h2>
      <MockBadge />
      <span class="spacer" style="flex: 1"></span>
      <select v-if="versions.length" :value="versionId" style="min-width: 200px" @change="switchVersion">
        <option v-for="v in versions" :key="v.version_id" :value="v.version_id">
          v{{ v.version_number }} · {{ v.version_id }} · {{ v.status === 'frozen' ? '已冻结' : '草稿' }}
        </option>
      </select>
      <span v-else-if="versionsPending" class="faint">版本列表接口待确认 P-18</span>
      <button v-if="can('studio.freeze')" class="btn" @click="showPipelineForm = !showPipelineForm">+ 新建 Pipeline</button>
    </div>

    <AppState v-if="loading" state="loading" />
    <AppState v-else-if="forbidden" state="forbidden" :error="error" />
    <AppState v-else-if="failed" state="error" :error="error" :retry="loadMeta" />
    <template v-else>
      <!-- 新建 Pipeline 内联表单（API-08，Maker） -->
      <div v-if="showPipelineForm" class="card">
        <div class="card-title">新建 Pipeline（API-08）</div>
        <div class="form-grid">
          <div class="form-field"><label>名称 <span class="req">*</span></label><input v-model="pipelineForm.name" type="text" /></div>
          <div class="form-field"><label>代码 <span class="req">*</span></label><input v-model="pipelineForm.code" type="text" /></div>
          <div class="form-field"><label>描述</label><input v-model="pipelineForm.description" type="text" /></div>
        </div>
        <div v-if="pipelineError" class="field-err mt-8">{{ pipelineError.friendly() }}（{{ pipelineError.errorCode }}）</div>
        <div class="btn-row mt-8">
          <button class="btn" @click="showPipelineForm = false">取消</button>
          <button class="btn primary" :disabled="pipelineSubmitting" @click="createPipeline">{{ pipelineSubmitting ? '提交中…' : '创建' }}</button>
        </div>
      </div>

      <div v-if="currentVersion?.is_immutable" class="tip-bar info mb-16">
        当前为冻结不可变版本：设计快照只读，禁止再生成（VER-409）。
      </div>
      <div v-else-if="versionsPending" class="tip-bar info mb-16">
        版本元数据读取接口待确认（Spec P-18）；版本冻结状态以服务端校验为准。
      </div>

      <!-- 需求 + 生成（API-09） -->
      <div class="card" v-if="!currentVersion?.is_immutable">
        <div class="card-title">需求输入 <span class="sub">API-09 · 发起生成</span></div>
        <PermissionBar action="studio.generate" />
        <div class="form-grid">
          <div class="form-field">
            <label>数据集成需求描述</label>
            <textarea v-model="generationForm.prompt" :disabled="!can('studio.generate')" placeholder="如：将 mysql_orders.orders 全量同步到 doris_orders 影子表，手机号与邮箱字段脱敏，质量通过后原子 Swap"></textarea>
          </div>
          <div class="form-field">
            <label>源 Profile 引用</label>
            <input v-model="generationForm.source_profile_ref" type="text" :disabled="!can('studio.generate')" />
          </div>
          <div class="form-field">
            <label>目标 Profile 引用</label>
            <input v-model="generationForm.target_profile_ref" type="text" :disabled="!can('studio.generate')" />
          </div>
          <div class="form-field">
            <label>Provider</label>
            <select v-model="generationForm.provider" :disabled="!can('studio.generate')">
              <option value="openai_compatible">openai_compatible</option>
              <option value="deepseek">deepseek</option>
              <option value="qwen">qwen</option>
            </select>
            <div class="form-hint">Provider 列表接口待确认 P-17，此处使用契约枚举。</div>
          </div>
        </div>
        <div v-if="generateError" class="field-err mt-8">{{ generateError.friendly() }}（{{ generateError.errorCode }}）</div>
        <div class="btn-row mt-8">
          <button v-if="can('studio.generate')" class="btn primary" :disabled="generating || !generationForm.prompt.trim()" @click="startGenerate">
            {{ generating ? '生成中…' : '发起生成' }}
          </button>
        </div>
      </div>

      <!-- 澄清表单（API-10） -->
      <div v-if="interrupted && question" class="card" style="border-color: rgba(251,191,36,0.5)">
        <div class="card-title">需要澄清 <span class="badge pending">等待回答</span></div>
        <div class="tip-bar warn">Agent 生成已中断，等待申请人回答（API-10）。仅申请人（Maker）可回答。</div>
        <div class="form-grid">
          <div class="form-field" v-for="f in question.fields || []" :key="f.name">
            <label>{{ question.question }} — {{ f.name }}<span class="req">*</span></label>
            <select v-if="f.type === 'enum'" v-model="answers[f.name]" :disabled="!can('studio.generate')">
              <option v-for="o in f.options || []" :key="o" :value="o">{{ o }}</option>
            </select>
            <select v-else-if="f.type === 'boolean'" v-model="answers[f.name]" :disabled="!can('studio.generate')">
              <option :value="true">是</option>
              <option :value="false">否</option>
            </select>
            <input v-else v-model="answers[f.name]" type="text" :disabled="!can('studio.generate')" />
          </div>
        </div>
        <div class="form-hint mt-8">thread_id：{{ threadId }}</div>
        <div v-if="answerError" class="field-err mt-8">{{ answerError.friendly() }}（{{ answerError.errorCode }}）</div>
        <div class="btn-row mt-8">
          <button v-if="can('studio.generate')" class="btn primary" :disabled="answering" @click="submitAnswers">{{ answering ? '提交中…' : '提交回答' }}</button>
        </div>
      </div>

      <AppState v-if="designError" state="error" :error="designError" :retry="loadDesign" />
      <AppState v-else-if="designNotReady" state="empty" title="设计尚未生成" text="API-11 返回 409：版本尚无可用设计，可先发起生成。" />

      <!-- 设计产物 -->
      <template v-if="design">
        <div class="card">
          <div class="card-title">生成设计 <span class="sub">API-11</span></div>
          <div class="tabs">
            <button class="tab" :class="{ active: designTabs === 'plan' }" @click="designTabs = 'plan'">EtlPlan</button>
            <button class="tab" :class="{ active: designTabs === 'hocon' }" @click="designTabs = 'hocon'">HOCON</button>
            <button class="tab" :class="{ active: designTabs === 'dag' }" @click="designTabs = 'dag'">DAG</button>
            <button class="tab" :class="{ active: designTabs === 'diff' }" @click="designTabs = 'diff'">字段 Diff</button>
            <button class="tab" :class="{ active: designTabs === 'gate' }" @click="designTabs = 'gate'">门禁</button>
            <button class="tab" :class="{ active: designTabs === 'mask' }" @click="designTabs = 'mask'">脱敏规则</button>
          </div>

          <div v-if="designTabs === 'plan'" class="table-wrap">
            <table class="table">
              <thead><tr><th>源</th><th>目标</th><th>调度</th></tr></thead>
              <tbody>
                <tr>
                  <td class="mono">{{ design.etl_plan_json?.source }}</td>
                  <td class="mono">{{ design.etl_plan_json?.target }}</td>
                  <td class="mono">{{ design.etl_plan_json?.schedule?.mode }}</td>
                </tr>
              </tbody>
            </table>
            <div class="form-hint mt-8">字段映射：</div>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>源字段</th><th>目标字段</th><th>转换</th></tr></thead>
                <tbody>
                  <tr v-for="m in design.etl_plan_json?.mappings || []" :key="m.source">
                    <td class="mono">{{ m.source }}</td>
                    <td class="mono">{{ m.target }}</td>
                    <td class="mono dim">{{ m.transform }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <HoconCodeBlock v-else-if="designTabs === 'hocon'" :code="design.hocon_text" />
          <div v-else-if="designTabs === 'dag'" class="card" style="background: var(--bg-deep); padding: 16px">
            <DagCanvas :nodes="design.dag?.nodes || []" :edges="design.dag?.edges || []" />
          </div>
          <DiffViewer v-else-if="designTabs === 'diff'" :base-version="design.diff?.base_version" :rows="design.diff?.rows || []" />
          <GateChecklist v-else-if="designTabs === 'gate'" :items="gateItems" />
          <div v-else-if="designTabs === 'mask'" class="table-wrap">
            <table class="table">
              <thead><tr><th>字段</th><th>原类型</th><th>处理后</th></tr></thead>
              <tbody>
                <tr v-for="m in maskTargets" :key="m.field">
                  <td class="mono">{{ m.field }}</td>
                  <td class="mono dim">{{ m.before }}</td>
                  <td class="mono" style="color: var(--ok)">{{ m.after }}</td>
                </tr>
              </tbody>
            </table>
            <div class="form-hint mt-8">脱敏字段值一律掩码，原始敏感样本不落前端。</div>
          </div>
        </div>

        <!-- 冻结 + 提交 -->
        <div class="card">
          <div class="card-title">冻结与提交</div>
          <PermissionBar action="studio.freeze" />
          <div class="btn-row">
            <button v-if="can('studio.freeze')" class="btn" disabled>冻结版本（接口待确认 P-18）</button>
            <span v-if="!gateAllPassed" class="faint">门禁 4/4 通过后方可冻结</span>
            <span v-else class="faint">冻结接口待确认 P-18；服务端仍会校验版本不可变状态。</span>
          </div>

          <div class="divider"></div>

          <div class="card-title">提交审批准备单 <span class="sub">API-12</span></div>
          <PermissionBar action="studio.submit" />
          <div class="form-grid" style="max-width: 520px">
            <div class="form-field">
              <label>调度模式</label>
              <select v-model="prepareForm.schedule_mode" :disabled="!can('studio.submit')">
                <option value="manual">manual</option>
              </select>
            </div>
            <div class="form-field">
              <label>最大输入行数</label>
              <input v-model.number="prepareForm.max_input_rows" type="number" min="1" :disabled="!can('studio.submit')" />
            </div>
            <div class="form-field">
              <label>最大时长（秒）</label>
              <input v-model.number="prepareForm.max_duration_seconds" type="number" min="1" :disabled="!can('studio.submit')" />
            </div>
            <div class="form-field">
              <label>质量契约引用</label>
              <input v-model="prepareForm.quality_contract_ref" type="text" :disabled="!can('studio.submit')" />
            </div>
          </div>
          <div v-if="prepareError" class="field-err mt-8">{{ prepareError.friendly() }}（{{ prepareError.errorCode }}）</div>
          <div class="btn-row mt-8">
            <button
              v-if="can('studio.submit')"
              class="btn primary"
              :disabled="preparing"
              @click="submitPrepare"
            >
              {{ preparing ? '提交中…' : '生成准备单并进入审批' }}
            </button>
            <span class="faint">版本不可变与门禁由服务端校验（PREP-409 / PREP-422）。</span>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
