/** WebSocket 实时连接，自动重连 + 心跳。 */
export class RealtimeSocket {
  constructor(path = '/ws/events') {
    this.path = path
    this.ws = null
    this.handlers = new Map()
    this.retry = 0
    this.timer = null
    this.heartbeat = null
    this.closed = false
  }

  url() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const token = localStorage.getItem('flower_token')
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${proto}://${location.host}${this.path}${qs}`
  }

  connect() {
    this.closed = false
    try {
      this.ws = new WebSocket(this.url())
    } catch {
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.retry = 0
      this.emit('open')
      this.heartbeat = setInterval(() => this.send({ action: 'ping' }), 25000)
    }
    this.ws.onmessage = (e) => {
      let msg
      try {
        msg = JSON.parse(e.data)
      } catch {
        return
      }
      this.emit(msg.type, msg)
      this.emit('*', msg)
    }
    this.ws.onclose = () => {
      clearInterval(this.heartbeat)
      this.emit('close')
      if (!this.closed) this.scheduleReconnect()
    }
    this.ws.onerror = () => this.ws?.close()
  }

  scheduleReconnect() {
    clearTimeout(this.timer)
    const delay = Math.min(1000 * 2 ** this.retry++, 15000)
    this.timer = setTimeout(() => this.connect(), delay)
  }

  send(obj) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj))
  }

  on(type, fn) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set())
    this.handlers.get(type).add(fn)
    return () => this.handlers.get(type)?.delete(fn)
  }

  emit(type, payload) {
    this.handlers.get(type)?.forEach((fn) => fn(payload))
  }

  close() {
    this.closed = true
    clearTimeout(this.timer)
    clearInterval(this.heartbeat)
    this.ws?.close()
  }
}
