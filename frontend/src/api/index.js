import http from './client'

/* ------------------------------ 认证 ------------------------------ */
export const authApi = {
  config: () => http.get('/api/auth/config'),
  login: (username, password) => http.post('/api/auth/login', { username, password })
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

  apply: (taskname, payload, timeout) =>
    http.post(`/api/task/apply/${encodeURIComponent(taskname)}`, payload, { params: { timeout } }),
  asyncApply: (taskname, payload) =>
    http.post(`/api/task/async-apply/${encodeURIComponent(taskname)}`, payload),
  sendTask: (taskname, payload) =>
    http.post(`/api/task/send-task/${encodeURIComponent(taskname)}`, payload)
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
  materialize: () => http.post('/api/config/materialize')
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
  restart: () => http.post('/api/system/restart')
}
