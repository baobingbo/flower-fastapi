import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

export const TASK_STATE_TYPE = {
  SUCCESS: 'success',
  FAILURE: 'danger',
  STARTED: 'primary',
  RECEIVED: 'info',
  PENDING: 'info',
  RETRY: 'warning',
  REVOKED: 'warning',
  REJECTED: 'danger',
  IGNORED: 'info'
}

export const TASK_STATE_COLOR = {
  SUCCESS: '#67c23a',
  FAILURE: '#f56c6c',
  STARTED: '#409eff',
  RECEIVED: '#909399',
  PENDING: '#c0c4cc',
  RETRY: '#e6a23c',
  REVOKED: '#b88230',
  REJECTED: '#c45656'
}

export function fmtTime(ts) {
  if (!ts) return '-'
  return dayjs(ts * 1000).format('YYYY-MM-DD HH:mm:ss')
}

export function fmtTimeShort(ts) {
  if (!ts) return '-'
  return dayjs(ts * 1000).format('HH:mm:ss')
}

export function fmtFromNow(ts) {
  if (!ts) return '-'
  return dayjs(ts * 1000).fromNow()
}

export function fmtRuntime(v) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  if (n < 1) return `${(n * 1000).toFixed(0)} ms`
  if (n < 60) return `${n.toFixed(3)} s`
  const m = Math.floor(n / 60)
  return `${m}m ${(n % 60).toFixed(1)}s`
}

export function fmtUptime(sec) {
  if (!sec && sec !== 0) return '-'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  if (d) return `${d}天 ${h}小时`
  if (h) return `${h}小时 ${m}分`
  if (m) return `${m}分 ${s}秒`
  return `${s}秒`
}

export function fmtBytes(kb) {
  if (!kb && kb !== 0) return '-'
  const units = ['KB', 'MB', 'GB', 'TB']
  let n = Number(kb)
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(2)} ${units[i]}`
}

export function truncate(text, len = 60) {
  if (text === null || text === undefined) return '-'
  const s = String(text)
  return s.length > len ? `${s.slice(0, len)}…` : s
}

export function prettyJson(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  const s = String(value)
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}
