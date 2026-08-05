import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

import { authApi, configApi, dashboardApi } from '@/api'
import { RealtimeSocket } from '@/api/ws'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

const MAX_EVENTS = 200
const MAX_TIMELINE = 360

export const useAppStore = defineStore('app', () => {
  const settings = useSettingsStore()

  /* ---------------- 认证 ---------------- */
  const authEnabled = ref(false)
  const authInfo = ref({})
  const user = ref(localStorage.getItem('flower_user') || '')
  const token = ref(localStorage.getItem('flower_token') || '')
  const authed = computed(() => !authEnabled.value || !!token.value)

  async function loadAuthConfig() {
    try {
      const cfg = await authApi.config()
      authInfo.value = cfg || {}
      authEnabled.value = !!cfg.auth_enabled
    } catch {
      authEnabled.value = false
    }
    return authEnabled.value
  }

  async function login(username, password) {
    const res = await authApi.login(username, password)
    token.value = res.access_token
    user.value = res.username || username
    localStorage.setItem('flower_token', token.value)
    localStorage.setItem('flower_user', user.value)
    return res
  }

  function logout() {
    token.value = ''
    user.value = ''
    localStorage.removeItem('flower_token')
    localStorage.removeItem('flower_user')
  }

  /* ---------------- 实时数据 ---------------- */
  const summary = ref({})
  const workers = ref([])
  const timeline = ref([])
  const eventFeed = ref([])
  const connected = ref(false)
  const filters = ref({ workers: [], task_types: [], states: [], queues: [], columns: [] })

  /** 通道运行态，供界面展示 */
  const channel = ref({
    mode: settings.transport,     // 'ws' | 'polling'
    lastUpdate: 0,                // 最近一次成功收到数据的时间戳
    errors: 0,                    // 连续失败次数
    latency: 0                    // 轮询模式下单次请求耗时（ms）
  })

  let socket = null
  let pollTimer = null
  let pollCursor = 0
  let polling = false

  /* ---------- WebSocket 实现 ---------- */
  function startSocket() {
    if (socket) return
    socket = new RealtimeSocket('/ws/events')
    socket.on('open', () => {
      connected.value = true
      channel.value.errors = 0
    })
    socket.on('close', () => (connected.value = false))
    socket.on('snapshot', (msg) => {
      summary.value = msg.summary || {}
      workers.value = msg.workers || []
      timeline.value = msg.timeline || []
      channel.value.lastUpdate = Date.now()
    })
    socket.on('summary', (msg) => {
      summary.value = msg.summary || {}
      channel.value.lastUpdate = Date.now()
    })
    socket.on('timeline', (msg) => {
      timeline.value = [...timeline.value, msg.point].slice(-MAX_TIMELINE)
      channel.value.lastUpdate = Date.now()
    })
    socket.on('event', (msg) => {
      pushEvents([msg.event])
    })
    // 主题目录发生变化（新增/删除文件）时立即刷新主题列表
    socket.on('themes_updated', () => {
      useThemeStore().refresh()
    })
    socket.connect()
  }

  function stopSocket() {
    socket?.close()
    socket = null
  }

  /* ---------- 轮询实现 ---------- */
  function pushEvents(list) {
    if (!list?.length) return
    const stamped = list.map((e) => ({ ...e, _id: `${Date.now()}-${Math.random()}` }))
    eventFeed.value = [...stamped, ...eventFeed.value].slice(0, MAX_EVENTS)
  }

  async function pollOnce() {
    if (polling) return
    polling = true
    const t0 = performance.now()
    try {
      const data = await dashboardApi.snapshot({
        since: pollCursor,
        events: settings.pollEvents,
        timeline_limit: MAX_TIMELINE,
        event_limit: 120
      })
      summary.value = data.summary || {}
      workers.value = data.workers || []
      timeline.value = data.timeline || []

      // 首次拉取只对齐游标，不把历史事件一次性灌进事件流
      if (pollCursor === 0) pushEvents((data.events || []).slice(0, 30))
      else pushEvents(data.events || [])
      pollCursor = data.cursor || pollCursor

      connected.value = true
      channel.value.errors = 0
      channel.value.latency = Math.round(performance.now() - t0)
      channel.value.lastUpdate = Date.now()
    } catch {
      channel.value.errors += 1
      // 连续 3 次失败才判定为断开，避免网络抖动导致状态灯乱闪
      if (channel.value.errors >= 3) connected.value = false
    } finally {
      polling = false
    }
  }

  function startPolling() {
    if (pollTimer) return
    pollCursor = 0
    pollOnce()
    pollTimer = setInterval(pollOnce, settings.pollInterval)
  }

  function stopPolling() {
    clearInterval(pollTimer)
    pollTimer = null
  }

  /* ---------- 通道调度 ---------- */
  function connect() {
    disconnect()
    channel.value.mode = settings.transport
    if (settings.transport === 'polling') startPolling()
    else startSocket()
  }

  function disconnect() {
    stopSocket()
    stopPolling()
    connected.value = false
  }

  /** 立即拉一次最新数据（任意通道都可用），用于手动刷新按钮 */
  async function refreshNow() {
    if (settings.transport === 'polling') return pollOnce()
    try {
      summary.value = await dashboardApi.summary()
      channel.value.lastUpdate = Date.now()
    } catch {
      /* 忽略 */
    }
  }

  // 通道类型变化 → 整体重建；轮询间隔变化 → 只重启定时器
  watch(
    () => settings.transport,
    () => {
      if (authed.value) connect()
    }
  )
  watch(
    () => settings.pollInterval,
    () => {
      if (pollTimer) {
        stopPolling()
        startPolling()
      }
    }
  )

  /* ---------------- 其它 ---------------- */
  async function loadFilters() {
    try {
      filters.value = await dashboardApi.filters()
    } catch {
      /* 忽略 */
    }
  }

  /** 读取服务端界面默认值（主题 / 通道 / 轮询间隔） */
  async function loadUiDefaults() {
    try {
      const ui = await configApi.ui()
      settings.applyServerDefaults(ui)
      return ui
    } catch {
      return null
    }
  }

  const mockMode = computed(() => !!summary.value.mock_mode)
  const transportLabel = computed(() =>
    settings.transport === 'polling' ? `轮询 ${settings.pollInterval}ms` : 'WebSocket'
  )

  return {
    authEnabled, authInfo, user, token, authed, loadAuthConfig, login, logout,
    summary, workers, timeline, eventFeed, connected, filters, mockMode,
    channel, transportLabel,
    connect, disconnect, refreshNow, loadFilters, loadUiDefaults
  }
})
