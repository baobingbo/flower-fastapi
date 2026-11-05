<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { configApi, themeApi, systemApi } from '@/api'
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

/** 编辑缓冲：key -> 值。只有真正改过的键才会提交 */
const draft = reactive({})
const dictText = reactive({})

const itemsByGroup = computed(() => {
  const map = {}
  for (const it of items.value) {
    // basic_auth_enabled 是"登录凭证管理"的总开关，嵌入到 basic_auth 编辑器内，不单独成行
    if (it.key === 'basic_auth_enabled') continue
    (map[it.group] ||= []).push(it)
  }
  return map
})

const dirtyKeys = computed(() =>
  items.value
    .filter((it) => {
      if (!it.editable) return false
      // 可编辑密文字段以 edit_value（明文）为基准判脏；
      // 否则若与脱敏后的 value 比较，未改也会被判为"脏"导致保存按钮常亮。
      const base = (it.secret && it.edit_value != null) ? it.edit_value : it.value
      if (it.type === 'dict') {
        let cur
        try {
          cur = JSON.parse(dictText[it.key] || '{}')
        } catch {
          return true
        }
        return !same(cur, base)
      }
      if (!(key(it) in draft)) return false
      return !same(draft[it.key], base)
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
    // 可编辑密文字段的草稿用 edit_value（明文），其余用脱敏后的 value
    const src = it.edit_value != null ? it.edit_value : it.value
    draft[it.key] = it.type === 'list' ? [...(src || [])] : src
    if (it.type === 'dict') {
      dictText[it.key] = JSON.stringify(src || {}, null, 2)
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
    ElMessage.success(res.message || '已保存')
    groups.value = res.config?.groups || groups.value
    items.value = res.config?.items || items.value
    seedDraft()
  } finally {
    saving.value = false
  }
}

async function resetAll() {
  await ElMessageBox.confirm(
    '将把所有在界面上改过的服务端配置恢复为进程启动时的取值，是否继续？',
    '恢复启动值',
    { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' }
  )
  const res = await configApi.reset(null)
  ElMessage.success(res.message)
  items.value = res.config?.items || items.value
  seedDraft()
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
      `${detail}\n点击确认后页面将在 2 秒后自动刷新。`,
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
  ElMessage.success('正在重启服务，2.5 秒后自动刷新页面…')
  setTimeout(() => location.reload(), 2500)
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
  ElMessage.success('界面偏好已恢复默认')
}

onMounted(() => {
  load()
  theme.refresh()
})

/* ---------------- 主题管理（上传/下载/删除用户主题） ---------------- */
const themeUploading = ref(false)
const themeFile = ref(null)

async function uploadTheme() {
  if (!themeFile.value) {
    ElMessage.warning('请先选择一个 .css 文件')
    return
  }
  themeUploading.value = true
  try {
    const res = await themeApi.upload(themeFile.value)
    ElMessage.success(res.message || '主题已添加')
    themeFile.value = null
    await theme.refresh()
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '上传失败'
    ElMessage.error(detail)
  } finally {
    themeUploading.value = false
  }
}

function onThemeFileChange(file) {
  // el-upload 的 raw 才是真实 File 对象
  themeFile.value = file?.raw || file
}

async function removeTheme(t) {
  await ElMessageBox.confirm(
    `确定删除用户主题「${t.name}」吗？该操作会同时删除主题目录下的 ${t.id}.css 文件。`,
    '删除主题',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
  const res = await themeApi.remove(t.id)
  ElMessage.success(res.message)
  await theme.refresh()
}

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
                <span class="field-desc">默认跟随操作系统的深浅色设置</span>
              </div>
              <el-radio-group
                :model-value="theme.preference"
                @update:model-value="theme.setPreference"
              >
                <el-radio-button value="auto">跟随系统</el-radio-button>
                <el-radio-button v-for="t in theme.themes" :key="t.id" :value="t.id">
                  {{ t.name }}
                </el-radio-button>
              </el-radio-group>
            </div>

            <div class="theme-cards">
              <button
                v-for="t in theme.themes"
                :key="t.id"
                class="theme-card"
                :class="{ active: theme.activeId === t.id }"
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
              </button>
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
            <span class="panel-title">主题管理（上传自定义主题）</span>
            <span class="text-muted panel-sub">
              按模板改完上传，或把 <span class="mono">xxx.css</span> 直接丢进主题目录，切换器会自动出现
            </span>
          </div>
          <div class="panel-body">
            <div class="tmpl-row">
              <a class="el-button el-button--default el-button--small" :href="themeApi.templateUrl" download>
                <el-icon><Download /></el-icon>&nbsp;下载主题模板
              </a>
              <span class="text-muted tmpl-tip">
                模板已 <code>@import './base.css'</code>，只改要覆盖的令牌即可；例如「极光晨曦」与「浅色」基本一致，只改几行。
              </span>
            </div>

            <el-upload
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

            <div class="theme-actions">
              <el-button
                type="primary"
                size="small"
                :loading="themeUploading"
                :disabled="!themeFile"
                @click="uploadTheme"
              >
                <el-icon><Upload /></el-icon>&nbsp;上传主题
              </el-button>
            </div>

            <div v-if="userThemes.length" class="user-theme-list">
              <div
                v-for="t in userThemes"
                :key="t.id"
                class="user-theme-item"
              >
                <span class="ut-swatch">
                  <i v-for="(c, i) in t.swatch" :key="i" :style="{ background: c }" />
                </span>
                <span class="ut-name">{{ t.name }}</span>
                <span class="ut-desc">{{ t.desc || t.id }}</span>
                <el-tag v-if="t.glass" size="small" effect="plain" round>液态</el-tag>
                <el-button
                  size="small"
                  type="danger"
                  text
                  @click="removeTheme(t)"
                >
                  <el-icon><Delete /></el-icon>&nbsp;删除
                </el-button>
              </div>
            </div>
            <div v-else class="text-muted ut-empty">尚未上传自定义主题</div>
          </div>
        </div>

        <div class="panel mb">
          <div class="panel-head">
            <span class="panel-title">数据通道</span>
            <span class="text-muted panel-sub">
              当前 {{ store.transportLabel }} ·
              {{ store.connected ? '已连接' : '未连接' }}
              <template v-if="settings.transport === 'polling' && store.channel.latency">
                · 上次耗时 {{ store.channel.latency }}ms
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
                  :max="30000"
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

      <!-- ============ 服务端配置分组 ============ -->
      <el-tab-pane
        v-for="g in groups.filter((x) => x.id !== 'ui')"
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

                <!-- 登录凭据：内部含"登录凭证管理"总开关，开启才展示并允许编辑用户 -->
                <CredentialsEditor
                  v-else-if="it.key === 'basic_auth'"
                  :model-value="(draft[it.key] || [])"
                  :enabled="draft['basic_auth_enabled'] ?? false"
                  :current-user="store.user"
                  @update:model-value="(v) => (draft[it.key] = v)"
                  @update:enabled="(v) => (draft['basic_auth_enabled'] = v)"
                  @commit="save"
                />
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

                <!-- 字符串：密文字段用密码框（默认遮罩、可点眼睛查看/编辑），其余明文 -->
                <el-input
                  v-else
                  v-model="draft[it.key]"
                  size="small"
                  style="width: 320px"
                  :type="it.secret ? 'password' : 'text'"
                  show-password
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

.theme-actions {
  margin: 12px 0 4px;
}

.user-theme-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
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
