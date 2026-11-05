<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  /** 用户凭据列表，元素形如 "user:pass" (已废弃，保留兼容) */
  modelValue: { type: Array, default: () => [] },
  /** 当前登录用户名（来自 app store），用于判定"本人"行是否可编辑 */
  currentUser: { type: String, default: '' },
  /** 总开关：是否展示并允许编辑登录凭据（已废弃，由RBAC管理） */
  enabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'update:enabled', 'commit'])

function toggleEnabled(v) {
  emit('update:enabled', v)
}

/* ---------- 本地行数据：直接可编辑，不依赖父组件回写 ---------- */
let _seq = 0
function makeRow(user, pass, opts = {}) {
  // B-04 配套：/api/config 只回掩码密码，输入框绑定「新密码」（初始留空=保持不变）；
  // originalPass 保留服务端原值（掩码），保存时密码为空就原样回传，由后端
  // 密码合并策略已废弃，改用 SQLite 存储
  // 掩码条目保留原密码、明文条目替换/追加，掩码不能新建用户）。
  const keepFilled = !!opts.isNew || !!opts.isDefault
  return {
    id: ++_seq,
    user,
    pass: keepFilled ? pass : '',
    originalPass: pass,
    isDefault: !!opts.isDefault,
    isNew: !!opts.isNew
  }
}

const rows = ref([])

function syncFromProp() {
  const list = props.modelValue || []
  if (!list.length) {
    rows.value = [makeRow('admin', 'admin', { isDefault: true })]
    return
  }
  rows.value = list.map((s) => {
    const [u = '', p = ''] = String(s).split(':', 2)
    return makeRow(u, p)
  })
}
syncFromProp()

/** 序列化本地行为外部所需的 list */
function serializeLocal() {
  // 密码留空 → 回传服务端原值（掩码 user:******），后端合并时保留原密码；
  // 输入了新密码 → 用新明文替换。新增/默认行 pass 始终有值，行为不变。
  return rows.value.map((r) => `${r.user}:${r.pass || r.originalPass}`)
}

/**
 * 仅在「外部数据确实不同于本地」时才同步（例如保存成功后父组件 reload）。
 * 不监听每次按键回写，避免抽屉被折叠、输入被冲掉。
 */
watch(
  () => props.modelValue,
  (val) => {
    const ext = JSON.stringify(val || [])
    const loc = JSON.stringify(serializeLocal())
    if (ext !== loc) syncFromProp()
  }
)

/* ---------- 展开 / 收起 ---------- */
const expandedRows = ref([])
function toggleExpand(id) {
  if (expandedRows.value.includes(id)) expandedRows.value = expandedRows.value.filter((x) => x !== id)
  else expandedRows.value.push(id)
}
function expand(id) {
  if (!expandedRows.value.includes(id)) expandedRows.value.push(id)
}

/* ---------- 判定 ---------- */
function isMe(row) {
  if (row.isDefault) return true // 默认占位账号（admin:admin）始终可编辑
  return !!props.currentUser && row.user === props.currentUser
}

/** 把本地行写回父组件（标记脏、可被顶部"保存修改"持久化） */
function emitUpdate() {
  emit('update:modelValue', serializeLocal())
}

/** 立即持久化（直接触发父组件的保存流程） */
function commitNow() {
  emitUpdate()
  emit('commit')
}

/* ---------- 新增用户 ---------- */
const adding = ref(false)
const newUser = ref({ user: '', pass: '' })

function startAdd() {
  newUser.value = { user: '', pass: '' }
  adding.value = true
}
function confirmAdd() {
  const u = (newUser.value.user || '').trim()
  const p = newUser.value.pass || ''
  if (!u) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (rows.value.find((r) => r.user === u)) {
    ElMessage.warning(`用户「${u}」已存在`)
    return
  }
  rows.value.push(makeRow(u, p || 'changeme', { isNew: true }))
  adding.value = false
  emitUpdate()
  ElMessage.success(`已添加用户「${u}」，记得点右上角「保存修改」生效`)
}
function cancelAdd() {
  adding.value = false
}

/** 删除用户（不能删自己） */
function removeUser(row) {
  if (isMe(row)) {
    ElMessage.warning('不能删除当前登录账号')
    return
  }
  rows.value = rows.value.filter((r) => r.id !== row.id)
  emitUpdate()
  ElMessage.success('已移除，记得点右上角「保存修改」生效')
}

const countText = computed(() => rows.value.length)
</script>

<template>
  <div class="cred-editor">
    <!-- 总开关（与"强制演示模式"同款默认关闭） -->
    <div class="cred-switch-row">
      <el-switch :model-value="enabled" size="small" @update:model-value="toggleEnabled" />
      <span class="cred-switch-label">登录凭证管理</span>
      <span class="cred-hint">
        {{ enabled ? '已开启：下方列出所有登录用户，可展开编辑自己的账号密码' : '已关闭：不展示用户凭据' }}
      </span>
    </div>

    <!-- ====== 开启时：Worker 风格用户卡片列表 + 展开抽屉 ====== -->
    <template v-if="enabled">
      <div class="cred-table-wrap">
        <!-- 表头工具栏 -->
        <div class="cred-toolbar">
          <span class="cred-count">
            共 <b>{{ countText }}</b> 个账号
            · 当前登录：<b>{{ currentUser || '—' }}</b>
          </span>
          <el-button size="small" @click="startAdd">
            <el-icon><Plus /></el-icon>&nbsp;新增人员
          </el-button>
        </div>

        <!-- 新增行 -->
        <div v-if="adding" class="cred-row cred-row--adding">
          <div class="cred-row-main">
            <div class="cred-avatar add">
              <el-icon><Plus /></el-icon>
            </div>
            <div class="cred-info">
              <el-input
                v-model="newUser.user"
                size="small"
                placeholder="用户名"
                style="width: 140px"
                @keyup.enter="confirmAdd"
              />
            </div>
            <div class="cred-pass">
              <el-input
                v-model="newUser.pass"
                size="small"
                type="password"
                placeholder="密码（留空=changeme）"
                style="width: 160px"
                show-password
                @keyup.enter="confirmAdd"
              />
            </div>
            <div class="cred-actions">
              <el-button size="small" type="primary" @click="confirmAdd">确认</el-button>
              <el-button size="small" @click="cancelAdd">取消</el-button>
            </div>
          </div>
        </div>

        <!-- 每个用户一行 -->
        <div
          v-for="row in rows"
          :key="row.id"
          class="cred-row"
          :class="{ 'cred-row--me': isMe(row), 'cred-row--readonly': !isMe(row) }"
        >
          <!-- 主行（始终可见） -->
          <div class="cred-row-main" @click="toggleExpand(row.id)">
            <div class="cred-avatar" :class="{ me: isMe(row), readonly: !isMe(row) }">
              <el-icon v-if="isMe(row)"><UserFilled /></el-icon>
              <el-icon v-else><Lock /></el-icon>
            </div>
            <div class="cred-info">
              <div class="cred-name">
                {{ row.user }}
                <el-tag v-if="row.isDefault" size="small" type="warning" effect="plain" round>默认</el-tag>
                <el-tag v-else-if="isMe(row)" size="small" type="success" effect="plain" round>本人</el-tag>
                <el-tag v-else size="small" type="info" effect="plain" round>其他</el-tag>
              </div>
              <div class="cred-sub">密码已配置 · {{ isMe(row) ? '可编辑' : '只读' }}</div>
            </div>
            <div class="cred-pass-display">
              <span class="cred-masked">••••••••</span>
            </div>
            <div class="cred-status">
              <el-tag v-if="isMe(row)" size="small" type="success" effect="light" round>可编辑</el-tag>
              <el-tag v-else size="small" type="info" effect="light" round>只读</el-tag>
            </div>
            <div class="cred-expand-hint">
              <el-icon :class="{ rotated: expandedRows.includes(row.id) }"><ArrowDown /></el-icon>
            </div>
          </div>

          <!-- 展开抽屉 -->
          <div v-if="expandedRows.includes(row.id)" class="cred-expand">
            <div class="cred-expand-body">
              <div class="cred-form-grid">
                <div class="cred-form-item">
                  <label>用户名</label>
                  <el-input
                    v-model="row.user"
                    size="small"
                    :disabled="!isMe(row)"
                    placeholder="登录用户名"
                    style="width: 200px"
                  />
                </div>
                <div class="cred-form-item">
                  <label>密码</label>
                  <el-input
                    v-model="row.pass"
                    size="small"
                    :disabled="!isMe(row)"
                    type="password"
                    show-password
                    :placeholder="!isMe(row)
                      ? '••••••••'
                      : (row.isNew || row.isDefault)
                        ? '输入新密码'
                        : '输入新密码（留空保持不变）'"
                    style="width: 200px"
                  />
                </div>
                <div class="cred-form-item cred-form-actions">
                  <template v-if="isMe(row)">
                    <el-button size="small" type="primary" @click="commitNow">
                      <el-icon><Check /></el-icon>&nbsp;保存修改
                    </el-button>
                    <el-button
                      v-if="!row.isDefault"
                      size="small"
                      type="danger"
                      text
                      @click="removeUser(row)"
                    >
                      <el-icon><Delete /></el-icon>&nbsp;删除
                    </el-button>
                  </template>
                  <span v-else class="text-muted" style="font-size: 12px">
                    仅当前登录用户「{{ row.user }}」可在自己的会话中修改此账号密码
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态提示 -->
        <div v-if="!rows.length && !adding" class="cred-empty">
          <span class="text-muted">暂无账号，点击「新增人员」添加</span>
        </div>
      </div>
    </template>

    <!-- ====== 关闭时：什么都不显示 ====== -->
    <template v-else>
      <div class="cred-off">
        <el-icon><Hide /></el-icon>
        <span>登录凭证管理已关闭，用户凭据不可见</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.cred-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.cred-switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cred-switch-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.cred-hint {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}

/* ---- 容器 ---- */
.cred-table-wrap {
  border: 1px solid var(--fu-border);
  border-radius: var(--fu-radius);
  overflow: hidden;
  background: var(--fu-surface-2);
}

/* ---- 工具栏 ---- */
.cred-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--fu-surface);
  border-bottom: 1px solid var(--fu-border);
}
.cred-count {
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
  flex: 1;
}
.cred-count b {
  color: var(--el-text-color-primary);
}

/* ---- 行 ---- */
.cred-rows {
  display: flex;
  flex-direction: column;
}
.cred-row {
  border-bottom: 1px solid var(--fu-border);
}
.cred-row:last-child {
  border-bottom: none;
}
.cred-row--adding {
  background: rgba(var(--fu-brand-rgb, 64, 158, 255), 0.04);
}

/* ---- 主行 ---- */
.cred-row-main {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.15s;
}
.cred-row-main:hover {
  background: rgba(0, 0, 0, 0.02);
}
.cred-row--me.cred-row--me .cred-row-main {
  background: rgba(var(--el-color-success-light-9, 19, 206, 129), 0.04);
}
.cred-row--me .cred-row-main:hover {
  background: rgba(var(--el-color-success-light-9, 19, 206, 129), 0.08);
}

/* 头像 */
.cred-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
  background: var(--fu-surface-3);
  color: var(--el-text-color-secondary);
  border: 2px solid var(--fu-border);
}
.cred-avatar.me {
  background: rgba(var(--el-color-success-light-9, 19, 206, 129), 0.12);
  color: var(--el-color-success);
  border-color: var(--el-color-success-light-5, 235, 247, 236);
}
.cred-avatar.readonly {
  color: var(--el-color-info);
}
.cred-avatar.add {
  background: rgba(var(--fu-brand-rgb, 64, 158, 255), 0.08);
  color: var(--fu-brand);
  border-color: var(--fu-brand-soft);
}

/* 信息区 */
.cred-info {
  flex: 1;
  min-width: 0;
}
.cred-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.cred-sub {
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
  margin-top: 2px;
}

/* 密码展示 */
.cred-pass-display {
  flex-shrink: 0;
}
.cred-masked {
  font-family: monospace;
  letter-spacing: 2px;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}

/* 状态标签 */
.cred-status {
  flex-shrink: 0;
}

/* 展开 arrow */
.cred-expand-hint {
  flex-shrink: 0;
  color: var(--el-text-color-placeholder);
  transition: transform 0.2s;
}
.cred-expand-hint .rotated {
  transform: rotate(180deg);
}

/* ---- 抽屉 ---- */
.cred-expand {
  border-top: 1px dashed var(--fu-border);
  background: rgba(0, 0, 0, 0.015);
}
.cred-expand-body {
  padding: 14px 18px 16px;
}
.cred-form-grid {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.cred-form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cred-form-item label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.cred-form-actions {
  align-self: flex-end;
  padding-bottom: 2px;
}

/* 空状态 */
.cred-empty {
  padding: 20px 14px;
  text-align: center;
}

/* 关闭占位 */
.cred-off {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border: 1px dashed var(--fu-border);
  border-radius: var(--fu-radius);
  background: var(--fu-surface-2);
  color: var(--el-text-color-placeholder);
  font-size: 12.5px;
}
.cred-off .el-icon {
  font-size: 15px;
}
</style>