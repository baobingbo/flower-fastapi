<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { configApi, themeApi, systemApi, auditApi } from '@/api'
import { useAppStore } from '@/stores/app'
import CredentialsEditor from '@/components/CredentialsEditor.vue'
import { POLL_MIN, POLL_MAX, TRANSPORT_OPTIONS, useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

defineOptions({ name: 'ConfigView' })

const store = useAppStore()
const settings = useSettingsStore()
const theme = useThemeStore()

const loading = ref(false)
const saving = ref(false)
const restarting = ref(false)
const materializing = ref(false)
const groups = ref([])
const items = ref([])
const runtimeFile = ref('')
const activeTab = ref('ui')
const showUploadDialog = ref(false)

/** 编辑缓冲：key -> 值。只有真正改过的键才会提交 */
const draft = reactive({})
const dictText = reactive({})

/** 配置搜索关键字：按 key/label/desc 忽略大小写包含匹配，跨所有服务端分组生效 */
const cfgSearch = ref('')

const itemsByGroup = computed(() => {
  const q = cfgSearch.value.trim().toLowerCase()
  const map = {}
  for (const it of items.value) {
    // 登录凭据管理已迁移至 RBAC 用户管理界面
    // auth-related configs handled by user management
    if (q) {
      const hay = `${it.key} ${it.label} ${it.desc || ''}`.toLowerCase()
      if (!hay.includes(q)) continue
    }
    (map[it.group] ||= []).push(it)
  }
  return map
})

/** 服务端分组（排除 ui 组）；搜索时仅保留有匹配项的分组 */
const serverGroups = computed(() =>
  groups.value
    .filter((x) => x.id !== 'ui')
    .filter((g) => (cfgSearch.value.trim() ? (itemsByGroup.value[g.id] || []).length > 0 : true))
)

/** 搜索匹配到的配置项总数（仅搜索时展示） */
const cfgMatchCount = computed(() =>
  serverGroups.value.reduce((n, g) => n + (itemsByGroup.value[g.id] || []).length, 0)
)

/** 当前 tab 是否为服务端分组（决定是否显示搜索框） */
const showCfgSearch = computed(() => serverGroups.value.some((g) => g.id === activeTab.value))

const dirtyKeys = computed(() =>
  items.value
    .filter((it) => {
      if (!it.editable) return false
      // 字典型：改动只落在 dictText，需单独比对，否则永远不算"脏"导致存不进
      if (it.type === 'dict') {
        let cur
        try {
          cur = JSON.parse(dictText[it.key] || '{}')
        } catch {
          return true
        }
        return !same(cur, it.value)
      }
      if (!(key(it) in draft)) return false
      return !same(draft[it.key], it.value)
    })
    .map((it) => it.key)
)

const modifiedCount = computed(() => items.value.filter((i) => i.modified).length)

/** 当前"脏"字段里，需要重启才能生效的那些（用于在保存旁显示"重启系统"） */
const dirtyNeedsRestart = computed(() =>
  items.value
    .filter((it) => dirtyKeys.value.includes(it.key) && it.restart_required)
    .map((it) => it.label)
)

function key(it) {
  return it.key
}

function same(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function seedDraft() {
  for (const it of items.value) {
    if (!it.editable) continue
    draft[it.key] = it.type === 'list' ? [...(it.value || [])] : it.value
    if (it.type === 'dict') {
      dictText[it.key] = JSON.stringify(it.value || {}, null, 2)
    }
  }
}

async function load() {
  loading.value = true
  try {
    const data = await configApi.get()
    groups.value = data.groups || []
    items.value = data.items || []
    runtimeFile.value = data.runtime_file || ''
    seedDraft()
  } catch (err) {
    ElMessage.error(err?.message || '配置加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  const changes = {}
  for (const k of dirtyKeys.value) {
    const it = items.value.find((i) => i.key === k)
    if (it?.type === 'dict') {
      try {
        changes[k] = JSON.parse(dictText[k] || '{}')
      } catch {
        ElMessage.error(`${it.label} 不是合法的 JSON`)
        return
      }
    } else {
      changes[k] = draft[k]
    }
  }
  if (!Object.keys(changes).length) {
    ElMessage.info('没有需要保存的改动')
    return
  }

  saving.value = true
  try {
    const res = await configApi.update(changes)
    const needRestart = dirtyNeedsRestart.value
    if (needRestart.length) {
      ElMessage.success(`已保存;${needRestart.length} 项需重启后生效:${needRestart.join('、')}`, { duration: 5000 })
    } else {
      ElMessage.success(res.message || '已保存')
    }
    groups.value = res.config?.groups || groups.value
    items.value = res.config?.items || items.value
    seedDraft()
  } catch (err) {
    ElMessage.error(err?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function resetAll() {
  try {
    await ElMessageBox.confirm(
      '将把所有在界面上改过的服务端配置恢复为进程启动时的取值，是否继续？',
      '恢复启动值',
      { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await configApi.reset(null)
    ElMessage.success(res.message)
    items.value = res.config?.items || items.value
    seedDraft()
  } catch (err) {
    ElMessage.error(err?.message || '恢复启动值失败')
  }
}

/** 生成完整配置：把当前所有配置连同中文注释写回配置文件（保留手工键）。 */
async function materializeConfig() {
  try {
    await ElMessageBox.confirm(
      '将把当前所有配置连同中文注释重新写入配置文件，方便你手工修改。\n' +
      '系统管理的字段会写出当前生效值；你手工添加、不在系统列表中的键会被原样保留。\n' +
      '注意：这是「重新排版 + 加注释」，不会丢失你已改的内容。',
      '生成完整配置',
      { type: 'info', confirmButtonText: '生成', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  materializing.value = true
  try {
    const res = await configApi.materialize()
    ElMessage.success(res.message + '，已刷新列表')
    await load()
  } catch (err) {
    ElMessage.error(err?.message || '生成配置失败')
  } finally {
    materializing.value = false
  }
}

/** 重启系统：把当前改动先落盘，再执行 manage.sh 脚本重启前后端服务。
 *  即使没有任何改动也可以点——用来手动重启服务。 */
async function restartSystem() {
  const needRestart = dirtyNeedsRestart.value
  const hasDirty = dirtyKeys.value.length > 0
  const detail = hasDirty
    ? `将先保存以下需要重启生效的改动并重启后端：\n${needRestart.join('、') || '（当前改动可热更新，仅做保存并重启）'}`
    : '当前没有待保存的改动，将直接重启后端进程。'
  try {
    await ElMessageBox.confirm(
      `${detail}\n点击确认后服务将重启，页面将在服务恢复后自动刷新。`,
      '重启系统',
      { type: 'warning', confirmButtonText: '重启', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  // 有改动则先保存落盘（runtime_config 会写 flowerui.runtime.env，重启后回放）
  if (hasDirty) {
    try {
      await save()
    } catch {
      return // save 内部已提示错误
    }
  }
  restarting.value = true
  try {
    await systemApi.restart()
  } catch {
    // 重启会掐断连接，拿不到回包也继续
  }
  // 轮询重启状态机（健康检查）：到终态后再提示/刷新
  waitForServiceRecovered()
}

/** 判定一次 restartStatus 响应是否已“恢复”（后端契约）：
 *  status=success，或 started_at 晚于 requested_at（新进程已接管）。 */
function restartRecovered(st) {
  if (!st) return false
  if (st.status === 'success') return true
  if (st.started_at && st.requested_at && Number(st.started_at) > Number(st.requested_at)) return true
  return false
}

/** 重启后健康检查：每 2s 轮询重启状态机，直到终态（success/failed/timeout）。
 *  旧进程已停、新进程未起期间请求会连接失败——静默继续轮询。
 *  恢复→提示并刷新；failed/timeout→展示 error/hint；前端 2 分钟兜底上限。 */
async function waitForServiceRecovered() {
  const waiting = ElMessage({
    message: '正在等待服务恢复…',
    type: 'info',
    showClose: false,
    duration: 0
  })
  const MAX_TRIES = 60
  for (let i = 0; i < MAX_TRIES; i++) {
    await new Promise((r) => setTimeout(r, 2000))
    let st = null
    try {
      st = await systemApi.restartStatus()
    } catch {
      /* 后端尚未就绪，继续轮询 */
    }
    if (!st) continue
    if (restartRecovered(st)) {
      waiting.close()
      ElMessage.success('服务已恢复')
      location.reload()
      return
    }
    if (st.status === 'failed' || st.status === 'timeout') {
      waiting.close()
      const detail = [st.error, st.hint].filter(Boolean).join('；')
      ElMessage.error(
        `重启${st.status === 'failed' ? '失败' : '超时'}${detail ? '：' + detail : ''}，请检查后端日志（可能 manage.sh 执行失败）`,
        { duration: 8000 }
      )
      return
    }
    // idle / in_progress：继续轮询
  }
  // 前端轮询上限（2 分钟）仍未到终态
  waiting.close()
  ElMessage.error('重启后 2 分钟内服务未恢复，请检查后端日志，可能 manage.sh 执行失败')
  try {
    await ElMessageBox.confirm('服务仍未恢复。是否强制刷新页面重试？', '等待超时', {
      type: 'warning',
      confirmButtonText: '强制刷新',
      cancelButtonText: '取消'
    })
    location.reload()
  } catch {
    /* 用户取消，保持现状 */
  }
}

/** 页面加载时检查是否有仍在进行的重启（重启期间用户手动刷新了页面），有则继续等待 */
async function checkRestartStatusOnMount() {
  let st = null
  try {
    st = await systemApi.restartStatus()
  } catch {
    return
  }
  if (st && st.status === 'in_progress') {
    waitForServiceRecovered()
  }
}

/** dict 类型的键值对编辑 */
function dictRows(k) {
  try {
    const obj = JSON.parse(dictText[k] || '{}')
    return Object.entries(obj).map(([kk, vv]) => ({ k: kk, v: vv }))
  } catch {
    return []
  }
}

function updateDictRow(k, index, field, value) {
  const rows = dictRows(k)
  if (!rows[index]) return
  rows[index][field] = value
  dictText[k] = JSON.stringify(Object.fromEntries(rows.map((r) => [r.k, r.v])), null, 2)
}

function addDictRow(k) {
  const rows = dictRows(k)
  rows.push({ k: '', v: '' })
  dictText[k] = JSON.stringify(Object.fromEntries(rows.map((r) => [r.k, r.v])), null, 2)
}

function removeDictRow(k, index) {
  const rows = dictRows(k)
  rows.splice(index, 1)
  dictText[k] = JSON.stringify(Object.fromEntries(rows.map((r) => [r.k, r.v])), null, 2)
}

function fmtValue(it) {
  if (it.value === null || it.value === undefined || it.value === '') return '—'
  if (Array.isArray(it.value)) return it.value.join(', ') || '—'
  if (typeof it.value === 'object') return JSON.stringify(it.value)
  if (typeof it.value === 'boolean') return it.value ? '开启' : '关闭'
  return `${it.value}${it.unit ? ' ' + it.unit : ''}`
}

/* ---------------- 界面偏好 ---------------- */
const pollSeconds = computed({
  get: () => settings.pollInterval,
  set: (v) => settings.setPollInterval(v)
})

function resetLocal() {
  settings.reset()
  theme.setPreference('auto')
  theme.setSchemeDefault('light', 'light')
  theme.setSchemeDefault('dark', 'dark')
  ElMessage.success('界面偏好已恢复默认')
}

/** 浏览器窗口关闭/刷新保护：有未保存改动时拦截 */
function onBeforeUnload(e) {
  if (!dirtyKeys.value.length) return
  e.preventDefault()
  e.returnValue = ''
}

onMounted(() => {
  load()
  theme.refresh()
  window.addEventListener('beforeunload', onBeforeUnload)
  checkRestartStatusOnMount()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})

/** 路由离开保护：有未保存的服务端配置改动时二次确认 */
onBeforeRouteLeave((to, from, next) => {
  if (!dirtyKeys.value.length) {
    next()
    return
  }
  ElMessageBox.confirm('有未保存的服务端配置改动，离开将丢失', '离开确认', {
    type: 'warning',
    confirmButtonText: '离开',
    cancelButtonText: '取消'
  })
    .then(() => next())
    .catch(() => next(false))
})

/** 搜索导致当前所在分组无匹配时，跳到第一个有匹配的分组，避免出现"空 tab" */
watch(cfgSearch, (q) => {
  if (!q.trim()) return
  const wasServer = groups.value.some((g) => g.id === activeTab.value && g.id !== 'ui')
  if (!wasServer) return
  if ((itemsByGroup.value[activeTab.value] || []).length === 0) {
    const first = serverGroups.value[0]
    if (first) activeTab.value = first.id
  }
})

/* ---------------- 主题管理（上传/下载/删除用户主题） ---------------- */
const themeUploading = ref(false)
const themeFile = ref(null)
const justUploaded = ref(null)
const uploadRef = ref(null)
/** 最近一次上传的 lint 警告列表（来自后端 theme_manager._lint） */
const uploadWarnings = ref([])
/** 上传前预览：客户端解析 CSS 文本（元数据 + 色块） */
const uploadPreview = ref(null)

/** 「跟随系统」卡片的当前映射说明 */
const autoDesc = computed(() => {
  const l = theme.themes.find((t) => t.id === theme.lightTheme)
  const d = theme.themes.find((t) => t.id === theme.darkTheme)
  return `浅色用「${l?.name || '浅色'}」，深色用「${d?.name || '深色'}」`
})

async function uploadTheme() {
  if (!themeFile.value) {
    ElMessage.warning('请先选择一个 .css 文件')
    return
  }
  themeUploading.value = true
  uploadWarnings.value = []
  const uploadingFile = themeFile.value
  try {
    const res = await themeApi.upload(themeFile.value)
    ElMessage.success(res.message || '主题已添加')
    uploadWarnings.value = res.theme?.warnings || []
    if (uploadWarnings.value.length) {
      ElMessage.warning(`主题已添加，但有 ${uploadWarnings.value.length} 条 lint 警告，详见下方`)
    }
    themeFile.value = null
    uploadPreview.value = null
    uploadRef.value?.clearFiles()
    await theme.refresh()
    // 展示刚上传的主题
    const uploaded = theme.themes.find(t => t.id === uploadingFile?.name?.replace(/\.css$/i, ''))
    if (uploaded) justUploaded.value = uploaded
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '上传失败'
    ElMessage.error(detail)
    uploadPreview.value = null
    uploadRef.value?.clearFiles()
  } finally {
    themeUploading.value = false
  }
}

function onThemeFileChange(file) {
  // el-upload 的 raw 才是真实 File 对象
  themeFile.value = file?.raw || file
  readThemePreview(themeFile.value)
}

/** 上传前预览：解析 CSS 顶部注释元数据（name/desc/scheme/swatch，
 *  与后端 _parse_meta 同格式）及 --fu-bg/--fu-surface/--fu-brand（或 --fu-chart-1）令牌色。 */
function parseThemePreview(text, fileName) {
  const id = (fileName || '').replace(/\.css$/i, '')
  const meta = {}
  const headerRe = /^[ \t]*\*?[ \t]*(name|desc|scheme|glass|swatch)[ \t]*:[ \t]*(.+?)[ \t]*$/gm
  let m
  while ((m = headerRe.exec(text)) !== null) {
    if (!(m[1] in meta)) meta[m[1]] = m[2].trim()
  }

  const tokenHex = (name) => {
    const mm = text.match(new RegExp(`--${name}\\s*:\\s*(#[0-9a-fA-F]{3,8})`))
    return mm ? mm[1] : null
  }

  let swatch = null
  if (meta.swatch) {
    const parts = meta.swatch.split(',').map((c) => c.trim())
    if (parts.length >= 3 && parts.slice(0, 3).every((c) => /^#[0-9a-fA-F]{3,8}$/.test(c))) {
      swatch = parts.slice(0, 3)
    }
  }
  if (!swatch) {
    const bg = tokenHex('fu-bg')
    const surface = tokenHex('fu-surface')
    const brand = tokenHex('fu-brand') || tokenHex('fu-chart-1')
    if (bg && surface && brand) swatch = [bg, surface, brand]
  }

  let scheme = meta.scheme
  if (scheme !== 'light' && scheme !== 'dark') {
    scheme = /color-scheme[ \t]*:[ \t]*dark/.test(text) ? 'dark' : null
  }

  return {
    fileName,
    name: meta.name || fileName,
    desc: meta.desc || '',
    scheme,
    swatch,
    hasMeta: !!(meta.name || meta.desc || meta.scheme || meta.swatch)
  }
}

/** 用 FileReader 读取选中的 CSS 文本并刷新预览；解析失败显示文件名 + 自动推导提示 */
function readThemePreview(file) {
  uploadPreview.value = null
  if (!file || typeof File === 'undefined' || !(file instanceof File)) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      uploadPreview.value = parseThemePreview(String(reader.result || ''), file.name)
    } catch {
      uploadPreview.value = { fileName: file.name, hasMeta: false }
    }
  }
  reader.onerror = () => {
    uploadPreview.value = { fileName: file.name, hasMeta: false }
  }
  reader.readAsText(file, 'utf-8')
}

async function removeTheme(t) {
  try {
    await ElMessageBox.confirm(
      `确定删除用户主题「${t.name}」吗？该操作会同时删除主题目录下的 ${t.id}.css 文件。`,
      '删除主题',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  // 删除前记录引用状态，成功后按引用做兜底补偿
  const wasActive = theme.activeId === t.id
  const wasLight = theme.lightTheme === t.id
  const wasDark = theme.darkTheme === t.id
  try {
    const res = await themeApi.remove(t.id)
    ElMessage.success(res.message)
    await theme.refresh()
    if (wasActive) {
      theme.setPreference('auto')
      ElMessage.warning('正在使用该主题，已切回「跟随系统」')
    }
    if (wasLight) {
      theme.setSchemeDefault('light', 'light')
      ElMessage.info('浅色默认已重置为内置「浅色」')
    }
    if (wasDark) {
      theme.setSchemeDefault('dark', 'dark')
      ElMessage.info('深色默认已重置为内置「深色」')
    }
  } catch (err) {
    ElMessage.error(err?.message || '删除主题失败')
  }
}

/** 上传成功后立即应用该主题并关闭弹窗 */
function applyJustUploaded() {
  if (!justUploaded.value) return
  theme.setPreference(justUploaded.value.id)
  showUploadDialog.value = false
}

/** 取消上传：清空已选文件并关闭弹窗 */
function cancelUpload() {
  uploadRef.value?.clearFiles()
  themeFile.value = null
  uploadWarnings.value = []
  uploadPreview.value = null
  showUploadDialog.value = false
}

/* ---------------- 操作审计 ---------------- */
const auditLoading = ref(false)
const auditLoaded = ref(false)
const auditRows = ref([])
const auditActions = ref([])
const auditActionFilter = ref('')

async function loadAudit() {
  auditLoading.value = true
  try {
    const params = { limit: 200 }
    if (auditActionFilter.value) params.action = auditActionFilter.value
    const res = await auditApi.list(params)
    auditRows.value = res.items || []
    auditLoaded.value = true
  } catch (err) {
    const status = err?.response?.status
    if (status === 401) {
      ElMessage.error('登录状态已失效，请重新登录')
    } else {
      const detail = err?.response?.data?.detail || err?.message || '审计日志加载失败'
      ElMessage.error(status === 404 ? `${detail}（若接口 404 请先重启后端加载新代码）` : detail)
    }
  } finally {
    auditLoading.value = false
  }
}

async function loadAuditActions() {
  try {
    const res = await auditApi.actions()
    auditActions.value = res.actions || []
  } catch {
    /* 筛选列表拉取失败可忽略 */
  }
}

/** 时间格式化：兼容 ISO8601 字符串（审计 ts）与 epoch 秒（备份 mtime） */
function fmtTs(v) {
  if (v == null || v === '') return '—'
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v)
  if (Number.isNaN(d.getTime())) return String(v)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 审计详情格式化：字符串直显；对象按 "key=value；key2=value2" 拼接。
 *  {old,new} 值显示为 "old 到 new"，其余对象值 JSON 紧凑化；长值省略（列有 overflow tooltip）。 */
function fmtDetail(detail) {
  if (detail == null || detail === '') return '—'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(fmtDetail).filter(Boolean).join('；') || '—'
  }
  if (typeof detail === 'object') {
    const parts = Object.entries(detail).map(([k, v]) => {
      let s
      if (v == null) s = ''
      else if (typeof v === 'string') s = v
      else if (typeof v === 'object' && ('old' in v || 'new' in v)) s = `${v.old ?? '∅'} 到 ${v.new ?? '∅'}`
      else s = JSON.stringify(v)
      if (s.length > 80) s = s.slice(0, 80) + '…'
      return `${k}=${s}`
    })
    return parts.join('；') || '—'
  }
  return String(detail)
}

/* ---------------- 配置备份 ---------------- */
const backupLoading = ref(false)
const backupLoaded = ref(false)
const backupRows = ref([])
const backupRuntimeFile = ref('')
const restoring = ref('')
const deleting = ref('')

async function loadBackups() {
  backupLoading.value = true
  try {
    const res = await configApi.backups()
    backupRows.value = res.backups || []
    backupRuntimeFile.value = res.runtime_file || ''
    backupLoaded.value = true
  } catch (err) {
    const status = err?.response?.status
    if (status === 401) {
      ElMessage.error('登录状态已失效，请重新登录')
    } else {
      const detail = err?.response?.data?.detail || err?.message || '配置备份加载失败'
      ElMessage.error(status === 404 ? `${detail}（若接口 404 请先重启后端加载新代码）` : detail)
    }
  } finally {
    backupLoading.value = false
  }
}

function fmtBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function restoreBackup(b) {
  try {
    await ElMessageBox.confirm(
      `将把运行配置回滚到备份「${b.name}」（差异键：${b.diff_keys?.length ? b.diff_keys.join('、') : '无'}）。\n回滚前系统会自动为当前配置新建一份备份。是否继续？`,
      '回滚配置',
      { type: 'warning', confirmButtonText: '回滚', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  restoring.value = b.name
  try {
    const res = await configApi.restoreBackup(b.name)
    ElMessage.success(res.message || '回滚成功')
    await loadBackups()
    await load() // 配置已变，重新读取列表与草稿
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '回滚失败')
  } finally {
    restoring.value = ''
  }
}

async function deleteBackup(b) {
  try {
    await ElMessageBox.confirm(`确定删除备份「${b.name}」吗？该操作不可恢复。`, '删除备份', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
    })
  } catch {
    return
  }
  deleting.value = b.name
  try {
    await configApi.deleteBackup(b.name)
    ElMessage.success('备份已删除')
    await loadBackups()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '删除备份失败')
  } finally {
    deleting.value = ''
  }
}

// 首次进入审计 / 备份 tab 时拉取一次
watch(activeTab, (tab) => {
  if (tab === 'audit' && !auditLoaded.value) {
    loadAudit()
    loadAuditActions()
  }
  if (tab === 'backup' && !backupLoaded.value) loadBackups()
})

/** 用户主题（非内置）列表，用于管理卡片展示 */
const userThemes = computed(() => theme.themes.filter((t) => !t.builtin))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">
          <el-icon><Setting /></el-icon>系统配置
        </h2>
        <div class="page-sub">
          查看运行中的全部配置，可热更新项支持直接修改；          改动会写入
          <span class="mono">{{ runtimeFile || 'flowerui.runtime.env' }}</span>
          （.env 格式），重启后依旧生效
        </div>
      </div>
      <div class="head-right">
        <el-tag v-if="modifiedCount" type="warning" size="small" effect="light" round>
          已覆盖 {{ modifiedCount }} 项
        </el-tag>
        <el-button size="small" :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>&nbsp;重新读取
        </el-button>
        <el-button size="small" :disabled="!modifiedCount" @click="resetAll">
          <el-icon><RefreshLeft /></el-icon>&nbsp;恢复启动值
        </el-button>
        <el-button
          type="primary"
          size="small"
          :loading="saving"
          :disabled="!dirtyKeys.length"
          @click="save"
        >
          保存修改{{ dirtyKeys.length ? `（${dirtyKeys.length}）` : '' }}
        </el-button>
        <el-button
          type="warning"
          size="small"
          :loading="restarting"
          :disabled="restarting"
          @click="restartSystem"
        >
          <el-icon><RefreshRight /></el-icon>&nbsp;重启系统
        </el-button>
        <el-button
          size="small"
          :loading="materializing"
          @click="materializeConfig"
        >
          生成完整配置
        </el-button>
      </div>
    </div>

    <div class="cfg-search" v-if="showCfgSearch">
      <el-input
        v-model="cfgSearch"
        placeholder="搜索配置项（名称/key/说明）"
        clearable
        size="small"
        style="max-width: 320px"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <span class="text-muted" v-if="cfgSearch.trim()">匹配 {{ cfgMatchCount }} 项</span>
    </div>

    <el-tabs v-model="activeTab" class="cfg-tabs">
      <!-- ============ 界面与实时通道 ============ -->
      <el-tab-pane label="界面与实时通道" name="ui">
        <div class="panel mb">
          <div class="panel-head">
            <span class="panel-title">主题外观</span>
            <span class="text-muted panel-sub">保存在浏览器本地，每个终端可以不一样</span>
          </div>
          <div class="panel-body">
            <div class="field">
              <div class="field-label">
                <span>主题模式</span>
                <span class="field-desc">点击下方卡片切换；「跟随系统」会按操作系统深浅色自动切换</span>
              </div>
            </div>

            <div class="theme-cards">
              <button
                class="theme-card"
                :class="{ active: theme.isAuto }"
                @click="theme.setPreference('auto')"
              >
                <span class="tc-preview auto-split">
                  <i class="tc-bar" style="background: #3f7ef8" />
                  <i class="tc-block" style="background: rgba(255, 255, 255, 0.75)" />
                  <i class="tc-block short" style="background: rgba(255, 255, 255, 0.5)" />
                </span>
                <span class="tc-name">
                  跟随系统
                  <el-tag size="small" effect="plain" round>自动</el-tag>
                </span>
                <span class="tc-desc">{{ autoDesc }}</span>
              </button>
              <button
                v-for="t in theme.themes"
                :key="t.id"
                class="theme-card"
                :class="{ active: theme.preference === t.id }"
                @click="theme.setPreference(t.id)"
              >
                <span class="tc-preview" :style="{ background: t.swatch[0] }">
                  <i class="tc-bar" :style="{ background: t.swatch[2] }" />
                  <i class="tc-block" :style="{ background: t.swatch[1] }" />
                  <i class="tc-block short" :style="{ background: t.swatch[1] }" />
                </span>
                <span class="tc-name">
                  {{ t.name }}
                  <el-tag v-if="t.glass" size="small" effect="plain" round>液态</el-tag>
                </span>
                <span class="tc-desc">{{ t.desc }}</span>
                <el-button
                  v-if="!t.builtin"
                  size="small"
                  type="danger"
                  text
                  class="tc-delete"
                  @click.stop="removeTheme(t)"
                >
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </button>
            </div>

            <div class="theme-upload-row">
              <el-button type="primary" size="small" @click="showUploadDialog = true">
                <el-icon><Upload /></el-icon>&nbsp;上传自定义主题
              </el-button>
              <a class="el-button el-button--default el-button--small tmpl-link"
                 :href="themeApi.templateUrl" download>
                <el-icon><Download /></el-icon> 下载主题模板
              </a>
              <span class="text-muted tmpl-tip">
                模板已 <code>@import './base.css'</code>，只改要覆盖的令牌即可
              </span>
            </div>

            <div class="field">
              <div class="field-label">
                <span>跟随系统时的映射</span>
                <span class="field-desc">
                  系统为浅色 / 深色时分别使用哪个主题，例如深色时用「科技液态」
                </span>
              </div>
              <div class="flex gap-3">
                <el-select
                  :model-value="theme.lightTheme"
                  size="small"
                  style="width: 160px"
                  @update:model-value="(v) => theme.setSchemeDefault('light', v)"
                >
                  <el-option
                    v-for="t in theme.themes.filter((x) => x.scheme === 'light')"
                    :key="t.id"
                    :label="`浅色 → ${t.name}`"
                    :value="t.id"
                  />
                </el-select>
                <el-select
                  :model-value="theme.darkTheme"
                  size="small"
                  style="width: 160px"
                  @update:model-value="(v) => theme.setSchemeDefault('dark', v)"
                >
                  <el-option
                    v-for="t in theme.themes.filter((x) => x.scheme === 'dark')"
                    :key="t.id"
                    :label="`深色 → ${t.name}`"
                    :value="t.id"
                  />
                </el-select>
              </div>
            </div>
          </div>
        </div>



        <div class="panel mb">
          <div class="panel-head">
            <span class="panel-title">数据通道</span>
            <span class="text-muted panel-sub">
              当前 {{ store.transportLabel }} ·
              {{ store.connected ? '已连接' : '未连接' }}
              <template v-if="settings.transport === 'ws'">
                · 重连 {{ store.channelHealth.wsReconnects }} 次
                <template v-if="store.channelHealth.wsLastMessageAt">
                  · 最近消息 {{ new Date(store.channelHealth.wsLastMessageAt).toTimeString().slice(0, 8) }}
                </template>
              </template>
              <template v-else>
                <template v-if="store.channelHealth.pollOk || store.channelHealth.pollFail">
                  · 最近 50 次：成功 {{ store.channelHealth.pollOk }} / 失败 {{ store.channelHealth.pollFail }}
                </template>
                <template v-if="store.channel.latency">
                  · 上次耗时 {{ store.channel.latency }}ms
                </template>
              </template>
            </span>
          </div>
          <div class="panel-body">
            <div class="transport-grid">
              <button
                v-for="opt in TRANSPORT_OPTIONS"
                :key="opt.value"
                class="tp-card"
                :class="{ active: settings.transport === opt.value }"
                @click="settings.setTransport(opt.value)"
              >
                <el-icon :size="18">
                  <component :is="opt.value === 'ws' ? 'Link' : 'Refresh'" />
                </el-icon>
                <span class="tp-name">{{ opt.label }}</span>
                <span class="tp-desc">{{ opt.desc }}</span>
              </button>
            </div>

            <div class="field" :class="{ disabled: settings.transport !== 'polling' }">
              <div class="field-label">
                <span>轮询间隔</span>
                <span class="field-desc">
                  仅轮询模式生效，范围 {{ POLL_MIN }} ~ {{ POLL_MAX }} 毫秒；越小越实时，服务端压力也越大
                </span>
              </div>
              <div class="poll-row">
                <el-slider
                  v-model="pollSeconds"
                  :min="POLL_MIN"
                  :max="POLL_MAX"
                  :step="500"
                  :disabled="settings.transport !== 'polling'"
                  style="max-width: 360px"
                />
                <el-input-number
                  v-model="pollSeconds"
                  :min="POLL_MIN"
                  :max="POLL_MAX"
                  :step="500"
                  size="small"
                  :disabled="settings.transport !== 'polling'"
                />
                <span class="text-muted">毫秒</span>
                <el-button
                  size="small"
                  :disabled="settings.transport !== 'polling'"
                  @click="store.refreshNow()"
                >
                  立即刷新
                </el-button>
              </div>
            </div>

            <div class="field" :class="{ disabled: settings.transport !== 'polling' }">
              <div class="field-label">
                <span>轮询时拉取事件流</span>
                <span class="field-desc">事件量较大时可关闭，仅保留概览与趋势</span>
              </div>
              <el-switch
                v-model="settings.pollEvents"
                :disabled="settings.transport !== 'polling'"
              />
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">交互偏好</span>
            <el-button size="small" text @click="resetLocal">恢复默认</el-button>
          </div>
          <div class="panel-body">
            <div class="field">
              <div class="field-label"><span>侧边导航默认收起</span></div>
              <el-switch v-model="settings.sidebarCollapsed" />
            </div>
            <div class="field">
              <div class="field-label"><span>表格密度</span></div>
              <el-radio-group v-model="settings.tableSize" size="small">
                <el-radio-button value="small">紧凑</el-radio-button>
                <el-radio-button value="default">标准</el-radio-button>
                <el-radio-button value="large">宽松</el-radio-button>
              </el-radio-group>
            </div>
            <div class="field">
              <div class="field-label"><span>页面切换动画</span></div>
              <el-switch v-model="settings.pageTransition" />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 操作审计 ============ -->
      <el-tab-pane label="操作审计" name="audit">
        <div class="panel" v-loading="auditLoading">
          <div class="panel-head">
            <span class="panel-title">
              <el-icon><Document /></el-icon>操作审计
            </span>
            <span class="text-muted panel-sub">最近 200 条 · 服务端记录（敏感值已脱敏）</span>
          </div>
          <div class="panel-body">
            <div class="audit-toolbar">
              <el-select
                v-model="auditActionFilter"
                size="small"
                clearable
                placeholder="按操作类型筛选"
                style="width: 210px"
                @change="loadAudit"
              >
                <el-option v-for="a in auditActions" :key="a" :label="a" :value="a" />
              </el-select>
              <el-button size="small" :loading="auditLoading" @click="loadAudit">
                <el-icon><Refresh /></el-icon>&nbsp;重新加载
              </el-button>
            </div>
            <el-table v-if="auditRows.length" :data="auditRows" :size="settings.tableSize" stripe>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ fmtTs(row.ts) }}</template>
              </el-table-column>
              <el-table-column prop="user" label="用户" width="130" show-overflow-tooltip />
              <el-table-column prop="action" label="操作" width="190" show-overflow-tooltip />
              <el-table-column label="结果" width="76">
                <template #default="{ row }">
                  <el-tag v-if="row.result === 'error'" size="small" type="danger" effect="plain">
                    失败
                  </el-tag>
                  <el-tag v-else size="small" type="success" effect="plain">成功</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="详情" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ fmtDetail(row.detail) }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else-if="!auditLoading" description="暂无审计记录" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 配置备份 ============ -->
      <el-tab-pane label="配置备份" name="backup">
        <div class="panel" v-loading="backupLoading">
          <div class="panel-head">
            <span class="panel-title">
              <el-icon><FolderOpened /></el-icon>配置备份
            </span>
            <span class="text-muted panel-sub">
              每次配置落盘 / 生成模板前自动备份（内容相同不重复），保留最近 20 份
            </span>
          </div>
          <div class="panel-body">
            <div class="audit-toolbar">
              <el-button size="small" :loading="backupLoading" @click="loadBackups">
                <el-icon><Refresh /></el-icon>&nbsp;重新加载
              </el-button>
              <span class="text-muted">
                当前生效文件：<code class="mono">{{ backupRuntimeFile || 'flowerui.runtime.env' }}</code>
              </span>
            </div>
            <el-table v-if="backupRows.length" :data="backupRows" size="small" stripe>
              <el-table-column label="备份文件" min-width="240" show-overflow-tooltip>
                <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
              </el-table-column>
              <el-table-column label="大小" width="90">
                <template #default="{ row }">{{ fmtBytes(row.size) }}</template>
              </el-table-column>
              <el-table-column label="备份时间" width="170">
                <template #default="{ row }">{{ fmtTs(row.mtime) }}</template>
              </el-table-column>
              <el-table-column label="差异键（相对当前）" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.diff_keys?.length ? row.diff_keys.join('、') : '—' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <el-button
                    size="small"
                    type="primary"
                    text
                    :loading="restoring === row.name"
                    @click="restoreBackup(row)"
                  >
                    回滚
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    text
                    :loading="deleting === row.name"
                    @click="deleteBackup(row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else-if="!backupLoading" description="暂无备份（配置首次落盘时自动创建）" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 上传主题悬浮弹窗 ============ -->
      <el-dialog
        v-model="showUploadDialog"
        title="上传自定义主题"
        width="480px"
        :close-on-click-modal="false"
      >
        <div class="upload-dialog-content">
          <el-upload
            ref="uploadRef"
            class="theme-uploader"
            drag
            accept=".css"
            :auto-upload="false"
            :limit="1"
            :show-file-list="true"
            :on-change="onThemeFileChange"
            :on-exceed="() => ElMessage.warning('一次只能上传一个文件')"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">把 CSS 文件拖到这里，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip text-muted">
                文件名即主题 id（需与 CSS 内的 <code>[data-theme='xxx']</code> 一致），仅支持 .css
              </div>
            </template>
          </el-upload>

          <div class="upload-preview" v-if="uploadPreview">
            <span class="up-swatch">
              <i
                v-for="(c, i) in (uploadPreview.swatch || ['#c8ccd6', '#dfe2e9', '#aeb4c2'])"
                :key="i"
                :style="{ background: c }"
              />
            </span>
            <span class="up-info">
              <span class="up-name">
                {{ uploadPreview.name || uploadPreview.fileName }}
                <el-tag v-if="uploadPreview.scheme === 'light'" size="small" effect="plain" round>浅色</el-tag>
                <el-tag v-else-if="uploadPreview.scheme === 'dark'" size="small" type="warning" effect="dark" round>深色</el-tag>
              </span>
              <span class="up-desc" v-if="uploadPreview.desc">{{ uploadPreview.desc }}</span>
              <span class="up-desc text-muted" v-else-if="!uploadPreview.hasMeta">无元数据，将自动推导</span>
            </span>
          </div>

          <div class="theme-actions">
            <el-button
              type="primary"
              :loading="themeUploading"
              :disabled="!themeFile"
              @click="uploadTheme"
            >
              <el-icon><Upload /></el-icon>&nbsp;上传主题
            </el-button>
            <el-button @click="cancelUpload">取消</el-button>
          </div>

          <div class="uploaded-preview" v-if="justUploaded">
            <div class="uploaded-preview-title">刚上传的主题</div>
            <div class="uploaded-theme-item">
              <span class="ut-swatch">
                <i v-for="(c, i) in justUploaded.swatch" :key="i" :style="{ background: c }" />
              </span>
              <span class="ut-name">{{ justUploaded.name }}</span>
              <span class="ut-desc">{{ justUploaded.desc || justUploaded.id }}</span>
              <el-tag v-if="justUploaded.glass" size="small" effect="plain" round>液态</el-tag>
              <el-button
                size="small"
                type="primary"
                @click="applyJustUploaded"
              >
                <el-icon><Check /></el-icon> 立即应用
              </el-button>
              <el-button
                size="small"
                type="danger"
                text
                @click="removeTheme(justUploaded); justUploaded = null"
              >
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </div>
            <div class="uploaded-warnings" v-if="uploadWarnings.length">
              <div class="uw-title">
                <el-icon><WarningFilled /></el-icon>Lint 警告（{{ uploadWarnings.length }}）
              </div>
              <div class="uw-item" v-for="(w, i) in uploadWarnings" :key="i">{{ w }}</div>
            </div>
          </div>
        </div>
      </el-dialog>

      <!-- ============ 服务端配置分组 ============ -->
      <el-tab-pane
        v-for="g in serverGroups"
        :key="g.id"
        :label="g.label"
        :name="g.id"
      >
        <div class="panel" v-loading="loading">
          <div class="panel-head">
            <span class="panel-title">
              <el-icon><component :is="g.icon" /></el-icon>{{ g.label }}
            </span>
            <span class="text-muted panel-sub">{{ g.desc }}</span>
          </div>
          <div class="panel-body cfg-list">
            <div
              v-for="it in itemsByGroup[g.id] || []"
              :key="it.key"
              class="cfg-item"
              :class="{ readonly: !it.editable }"
            >
              <div class="cfg-meta">
                <div class="cfg-name">
                  {{ it.label }}
                  <span class="mono cfg-key">{{ it.key }}</span>
                  <el-tag v-if="it.modified" size="small" type="warning" effect="plain" round>
                    已覆盖
                  </el-tag>
                  <el-tag v-if="it.restart_required" size="small" type="info" effect="plain" round>
                    需重启
                  </el-tag>
                  <el-tag v-if="it.secret" size="small" type="danger" effect="plain" round>
                    敏感
                  </el-tag>
                  <el-tooltip v-if="it.todo" :content="it.todo_reason" placement="top">
                    <el-tag size="small" type="warning" effect="dark" round class="cfg-todo">
                      <el-icon><WarningFilled /></el-icon>&nbsp;待完善
                    </el-tag>
                  </el-tooltip>
                </div>
                <div v-if="it.desc" class="cfg-desc">{{ it.desc }}</div>
              </div>

              <div class="cfg-control">
                <!-- 只读 -->
                <span v-if="!it.editable" class="mono cfg-ro">{{ fmtValue(it) }}</span>

                <!-- 布尔 -->
                <el-switch v-else-if="it.type === 'bool'" v-model="draft[it.key]" />

                <!-- 枚举 -->
                <el-select
                  v-else-if="it.type === 'enum'"
                  v-model="draft[it.key]"
                  size="small"
                  style="width: 190px"
                >
                  <el-option v-for="o in it.options" :key="o" :label="o" :value="o" />
                </el-select>

                <!-- 数值 -->
                <div v-else-if="it.type === 'int' || it.type === 'float'" class="flex gap-2">
                  <el-input-number
                    v-model="draft[it.key]"
                    size="small"
                    :min="it.min ?? undefined"
                    :max="it.max ?? undefined"
                    :step="it.type === 'float' ? 100 : 1"
                    controls-position="right"
                  />
                  <span v-if="it.unit" class="text-muted">{{ it.unit }}</span>
                </div>

                <!-- 字典（任务→队列映射） -->
                <div v-else-if="it.type === 'dict'" class="dict-editor">
                  <div v-for="(row, i) in dictRows(it.key)" :key="i" class="dict-row">
                    <el-input
                      :model-value="row.k"
                      size="small"
                      placeholder="任务名"
                      @update:model-value="(v) => updateDictRow(it.key, i, 'k', v)"
                    />
                    <el-icon class="dict-arrow"><Right /></el-icon>
                    <el-input
                      :model-value="row.v"
                      size="small"
                      placeholder="队列名"
                      @update:model-value="(v) => updateDictRow(it.key, i, 'v', v)"
                    />
                    <el-button size="small" text type="danger" @click="removeDictRow(it.key, i)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                  <el-button size="small" text @click="addDictRow(it.key)">
                    <el-icon><Plus /></el-icon>&nbsp;新增映射
                  </el-button>
                </div>

                <el-input
                  v-else-if="it.type === 'list'"
                  :model-value="(draft[it.key] || []).join(', ')"
                  size="small"
                  placeholder="逗号分隔"
                  style="width: 320px"
                  @update:model-value="
                    (v) => (draft[it.key] = v.split(',').map((x) => x.trim()).filter(Boolean))
                  "
                />

                <!-- 字符串 -->
                <el-input
                  v-else
                  v-model="draft[it.key]"
                  size="small"
                  style="width: 320px"
                  :placeholder="it.label"
                />
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.cfg-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.audit-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.cfg-search {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

/* ---------------- 通用字段行 ---------------- */
.field {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 0;
  border-bottom: 1px dashed var(--fu-border);
}

.field:last-child {
  border-bottom: none;
}

.field.disabled {
  opacity: 0.55;
}

.field-label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 13.5px;
  font-weight: 560;
  color: var(--fu-text);
  min-width: 0;
}

.field-desc {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--fu-text-muted);
  line-height: 1.6;
  max-width: 520px;
}

.poll-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* ---------------- 主题卡片 ---------------- */
.theme-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px dashed var(--fu-border);
}

.theme-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1.5px solid var(--fu-border);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
  cursor: pointer;
  text-align: left;
  transition: var(--fu-transition);
  font-family: inherit;
}

.theme-card:hover {
  border-color: var(--fu-border-strong);
  transform: translateY(-1px);
}

.theme-card.active {
  border-color: var(--fu-brand);
  box-shadow: 0 0 0 3px var(--fu-brand-soft);
}

.tc-preview {
  position: relative;
  height: 62px;
  border-radius: var(--fu-radius-sm);
  overflow: hidden;
  border: 1px solid var(--fu-border);
  display: block;
}

.tc-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 20px;
  opacity: 0.85;
}

.tc-block {
  position: absolute;
  left: 28px;
  right: 10px;
  top: 12px;
  height: 14px;
  border-radius: 4px;
  opacity: 0.9;
}

.tc-block.short {
  top: 34px;
  right: 46px;
  height: 12px;
}

.tc-name {
  font-size: 13px;
  font-weight: 620;
  color: var(--fu-text);
  display: flex;
  align-items: center;
  gap: 6px;
}

.tc-desc {
  font-size: 11.5px;
  color: var(--fu-text-muted);
  line-height: 1.5;
}

.tc-delete {
  align-self: flex-end;
  margin-top: auto;
  font-size: 12px;
  padding: 2px 6px;
}

/* ---------------- 通道卡片 ---------------- */
.transport-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--fu-border);
}

.tp-card {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-areas: 'icon name' 'icon desc';
  gap: 2px 12px;
  align-items: center;
  padding: 14px;
  border: 1.5px solid var(--fu-border);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
  cursor: pointer;
  text-align: left;
  transition: var(--fu-transition);
  font-family: inherit;
  color: var(--fu-text);
}

.tp-card .el-icon {
  grid-area: icon;
  color: var(--fu-text-muted);
}

.tp-card:hover {
  border-color: var(--fu-border-strong);
}

.tp-card.active {
  border-color: var(--fu-brand);
  box-shadow: 0 0 0 3px var(--fu-brand-soft);
}

.tp-card.active .el-icon {
  color: var(--fu-brand);
}

.tp-name {
  grid-area: name;
  font-size: 13.5px;
  font-weight: 620;
}

.tp-desc {
  grid-area: desc;
  font-size: 11.5px;
  color: var(--fu-text-muted);
  line-height: 1.55;
}

/* ---------------- 服务端配置列表 ---------------- */
.cfg-list {
  display: flex;
  flex-direction: column;
}

.cfg-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 13px 0;
  border-bottom: 1px dashed var(--fu-border);
}

.cfg-item:last-child {
  border-bottom: none;
}

/* ---------------- 主题管理 ---------------- */
.tmpl-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.tmpl-tip,
.tmpl-row code {
  font-size: 11.5px;
  color: var(--fu-text-muted);
}

.theme-uploader {
  max-width: 560px;
}

/* ---------------- 上传前预览卡 ---------------- */
.upload-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 9px 12px;
  border: 1px dashed var(--fu-border-strong);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
}

.up-swatch {
  display: inline-flex;
  width: 46px;
  height: 22px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--fu-border);
  flex-shrink: 0;
}

.up-swatch i {
  flex: 1;
}

.up-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.up-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--fu-text);
  display: flex;
  align-items: center;
  gap: 6px;
}

.up-desc {
  font-size: 11.5px;
  color: var(--fu-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.theme-actions {
  margin: 12px 0 4px;
}

.theme-upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--fu-border);
}

.tmpl-link {
  text-decoration: none;
}

.tmpl-link:hover {
  text-decoration: none;
}

.tmpl-tip,
.tmpl-row code {
  font-size: 11.5px;
  color: var(--fu-text-muted);
}

.user-theme-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}

.uploaded-themes-list {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--fu-border);
}

.uploaded-themes-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fu-text);
  margin-bottom: 10px;
}

.uploaded-theme-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--fu-border);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
  margin-bottom: 8px;
}

.uploaded-theme-item:last-child {
  margin-bottom: 0;
}

.user-theme-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--fu-border);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
}

.ut-swatch {
  display: inline-flex;
  width: 46px;
  height: 22px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--fu-border);
  flex-shrink: 0;
}

.ut-swatch i {
  flex: 1;
}

.ut-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--fu-text);
}

.ut-desc {
  font-size: 11.5px;
  color: var(--fu-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.ut-empty {
  margin-top: 12px;
  font-size: 12px;
}

/* ---------------- 上传 lint 警告 ---------------- */
.uploaded-warnings {
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px solid var(--fu-warning);
  border-radius: var(--fu-radius);
  background: var(--fu-warning-soft);
}

.uw-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--fu-warning);
  margin-bottom: 4px;
}

.uw-item {
  position: relative;
  font-size: 12px;
  color: var(--fu-text-secondary);
  line-height: 1.7;
  padding-left: 14px;
}

.uw-item::before {
  content: "·";
  position: absolute;
  left: 4px;
  color: var(--fu-warning);
  font-weight: 700;
}

/* 「跟随系统」卡片预览：左半浅色 / 右半深色 */
.tc-preview.auto-split {
  background: linear-gradient(135deg, #f4f6fa 50%, #14161c 50%);
}

.cfg-meta {
  min-width: 0;
  flex: 1;
}

.cfg-name {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 13.5px;
  font-weight: 560;
  color: var(--fu-text);
}

.cfg-key {
  font-size: 11px;
  color: var(--fu-text-muted);
  background: var(--fu-surface-2);
  padding: 1px 6px;
  border-radius: var(--fu-radius-xs);
}

.cfg-todo {
  cursor: help;
}

.cfg-todo .el-icon {
  vertical-align: -2px;
}

.cfg-desc {
  font-size: 11.5px;
  color: var(--fu-text-muted);
  line-height: 1.6;
  margin-top: 4px;
  max-width: 640px;
}

.cfg-control {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 200px;
}

.cfg-ro {
  color: var(--fu-text-secondary);
  word-break: break-all;
  text-align: right;
  max-width: 360px;
}

.dict-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.dict-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dict-row .el-input {
  width: 168px;
}

.dict-arrow {
  color: var(--fu-text-muted);
}

@media (max-width: 860px) {
  .cfg-item,
  .field {
    flex-direction: column;
    align-items: stretch;
  }

  .cfg-control {
    justify-content: flex-start;
  }
}
</style>
