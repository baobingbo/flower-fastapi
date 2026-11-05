import http from './client'

/* ------------------------------ 认证 ------------------------------ */
export const authApi = {
  config: () => http.get('/api/auth/config'),
  login: (username, password) => http.post('/api/auth/login', { username, password }),
  /** 通用 OAuth2 授权码流程：返回 {redirect_url}，前端拿到后整页跳转提供方授权页 */
  oauthLogin: () => http.get('/api/auth/oauth2/login')
}

/* ------------------------------ 用户管理 ------------------------------ */
export const userApi = {
  changePassword: (oldPassword, newPassword) =>
    http.post('/api/auth/password/change', { old_password: oldPassword, new_password: newPassword }),
  logout: () => http.post('/api/auth/logout'),
  sessions: () => http.get('/api/auth/sessions'),
  deleteSession: (jti) => http.delete(`/api/auth/sessions/${encodeURIComponent(jti)}`),
  loginLogs: (params = {}) => http.get('/api/auth/login-logs', { params })
}

/* ------------------------------ Dashboard ------------------------------ */
export const dashboardApi = {
  summary: () => http.get('/api/dashboard/summary'),
  timeline: (limit = 120) => http.get('/api/dashboard/timeline', { params: { limit } }),
  /** 轮询模式主力接口：一次拿齐 summary + workers + timeline + 增量事件 */
  snapshot: (params) => http.get('/api/dashboard/snapshot', { params, silent: true }),
  filters: () => http.get('/api/dashboard/filters'),
  distribution: (top = 10) => http.get('/api/dashboard/task-distribution', { params: { top } }),
  system: () => http.get('/api/system')
}

/* ------------------------------ Workers ------------------------------ */
export const workerApi = {
  table: (refresh = false) => http.get('/api/workers/table', { params: { refresh } }),
  list: (params) => http.get('/api/workers', { params }),
  /** F-05：导出 Worker 列表（blob，浏览器下载） */
  export: (params) => http.get('/api/workers/export', { params, responseType: 'blob', timeout: 60000 }),
  detail: (name, refresh = true) =>
    http.get(`/api/worker/${encodeURIComponent(name)}`, { params: { refresh } }),

  shutdown: (name) => http.post(`/api/worker/shutdown/${encodeURIComponent(name)}`),
  poolRestart: (name) => http.post(`/api/worker/pool/restart/${encodeURIComponent(name)}`),
  poolGrow: (name, n) => http.post(`/api/worker/pool/grow/${encodeURIComponent(name)}`, null, { params: { n } }),
  poolShrink: (name, n) => http.post(`/api/worker/pool/shrink/${encodeURIComponent(name)}`, null, { params: { n } }),
  poolAutoscale: (name, min, max) =>
    http.post(`/api/worker/pool/autoscale/${encodeURIComponent(name)}`, null, { params: { min, max } }),
  addConsumer: (name, queue) =>
    http.post(`/api/worker/queue/add-consumer/${encodeURIComponent(name)}`, null, { params: { queue } }),
  cancelConsumer: (name, queue) =>
    http.post(`/api/worker/queue/cancel-consumer/${encodeURIComponent(name)}`, null, { params: { queue } })
}

/* ------------------------------ Tasks ------------------------------ */
export const taskApi = {
  table: (params) => http.get('/api/tasks/table', { params }),
  list: (params) => http.get('/api/tasks', { params }),
  info: (id) => http.get(`/api/task/info/${id}`),
  types: () => http.get('/api/task/types'),
  registered: () => http.get('/api/task/registered'),
  result: (id, timeout) => http.get(`/api/task/result/${id}`, { params: { timeout } }),

  revoke: (id, terminate = false, signal = 'SIGTERM') =>
    http.post(`/api/task/revoke/${id}`, null, { params: { terminate, signal } }),
  abort: (id) => http.post(`/api/task/abort/${id}`),
  rateLimit: (taskname, workername, ratelimit) =>
    http.post(`/api/task/rate-limit/${encodeURIComponent(taskname)}`, null,
      { params: { workername, ratelimit } }),
  timeout: (taskname, workername, soft, hard) =>
    http.post(`/api/task/timeout/${encodeURIComponent(taskname)}`, null,
      { params: { workername, soft, hard } }),

  // B-06 配套：apply 等待最长 300s（后端上限），请求级超时必须大于全局 30s，否则 axios 会提前中断
  apply: (taskname, payload, timeout) =>
    http.post(`/api/task/apply/${encodeURIComponent(taskname)}`, payload, {
      params: { timeout },
      timeout: Math.max(35, (Number(timeout) || 30) + 5) * 1000
    }),
  asyncApply: (taskname, payload) =>
    http.post(`/api/task/async-apply/${encodeURIComponent(taskname)}`, payload),
  sendTask: (taskname, payload) =>
    http.post(`/api/task/send-task/${encodeURIComponent(taskname)}`, payload),

  /** F-04：一键重试（复用原参数重新投递），返回 { 'task-id': 新id } */
  retry: (id, params) =>
    http.post(`/api/task/retry/${encodeURIComponent(id)}`, null, { params, timeout: 60000 }),
  /** F-05：导出任务列表（blob，浏览器下载） */
  export: (params) => http.get('/api/tasks/export', { params, responseType: 'blob', timeout: 120000 })
}

/* ------------------------------ Broker ------------------------------ */
export const brokerApi = {
  overview: () => http.get('/api/broker'),
  queues: () => http.get('/api/queues/length')
}

/* ------------------------------ 配置 ------------------------------ */
export const configApi = {
  /** 界面默认值，免鉴权，登录页也会用到 */
  ui: () => http.get('/api/config/ui', { silent: true }),
  get: () => http.get('/api/config'),
  update: (changes) => http.put('/api/config', { changes }),
  reset: (keys = null) => http.post('/api/config/reset', { keys }),
  /** 生成一份完整带注释的默认配置模板（保留手工键） */
  materialize: () => http.post('/api/config/materialize'),
  /** #5 配置备份列表（新→旧，diff_keys 为与当前文件的差异键） */
  backups: () => http.get('/api/config/backups'),
  /** #5 回滚到指定备份（回滚前会先给当前文件建新备份） */
  restoreBackup: (name) => http.post('/api/config/backups/restore', { name }),
  /** #5 删除指定备份 */
  deleteBackup: (name) => http.delete('/api/config/backups', { data: { name } })
}

/* ------------------------------ 主题（运行时目录发现） ------------------------------ */
export const themeApi = {
  /** 列出主题目录中全部用户主题 */
  list: () => http.get('/api/themes', { silent: true }),
  /** 上传一个主题 CSS 文件 */
  upload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/api/themes', fd)
  },
  /** 删除一个用户主题 */
  remove: (id) => http.delete(`/api/themes/${encodeURIComponent(id)}`),
  /** 模板文件下载地址 */
  templateUrl: '/api/themes/files/_template.css'
}

/* ------------------------------ 系统操作 ------------------------------ */
export const systemApi = {
  /** 重启后端进程，使需要重启才生效的配置落地 */
  restart: () => http.post('/api/system/restart'),
  /** #4 重启状态机（健康检查，免鉴权）：
   *  {status: idle|in_progress|success|failed|timeout, requested_at, completed_at,
   *   pid, current_pid, started_at, script, interpreter, error, hint}
   *  started_at > requested_at 即新进程已接管 */
  restartStatus: () => http.get('/api/system/restart/status', { silent: true })
}


/* ------------------------------ 用户管理 ------------------------------ */
export const usersApi = {
  list: () => http.get('/api/users'),
  create: (data) => http.post('/api/users', data),
  update: (username, data) => http.put(`/api/users/${encodeURIComponent(username)}`, data),
  delete: (username) => http.delete(`/api/users/${encodeURIComponent(username)}`),
  changePassword: (username, password) => http.post(`/api/users/${encodeURIComponent(username)}/password`, { password }),
  getRoles: (username) => http.get(`/api/users/${encodeURIComponent(username)}/roles`),
  assignRole: (username, role) => http.post(`/api/users/${encodeURIComponent(username)}/roles`, { role }),
  removeRole: (username, role) => http.delete(`/api/users/${encodeURIComponent(username)}/roles/${encodeURIComponent(role)}`),
}

/* ------------------------------ 角色管理 ------------------------------ */
export const rolesApi = {
  list: () => http.get('/api/roles'),
  create: (data) => http.post('/api/roles', data),
  update: (name, data) => http.put(`/api/roles/${encodeURIComponent(name)}`, data),
  delete: (name) => http.delete(`/api/roles/${encodeURIComponent(name)}`),
}

/* ------------------------------ 权限管理 ------------------------------ */
export const permissionsApi = {
  list: () => http.get('/api/permissions'),
}
/* ------------------------------ 审计日志 ------------------------------ */
export const auditApi = {
  /** #6 审计记录分页查询（倒序，最新在前）；过滤：user / action / start / end */
  list: (params = {}) => http.get('/api/audit', { params }),
  /** 已出现过的 action 类型列表（供筛选下拉） */
  actions: () => http.get('/api/audit/actions', { silent: true })
}