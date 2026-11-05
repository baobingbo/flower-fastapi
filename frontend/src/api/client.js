import axios from 'axios'
import { useAppStore } from '@/stores/app'

const http = axios.create({ baseURL: '/', timeout: 30000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('flower_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 错误统一处理：只负责 401 的认证清理。
// G3：拦截器不再弹 ElMessage.error——错误 toast 由各视图 catch 负责，消除双弹；
// silent 语义（snapshot / config.ui / themes.list 等）交给各调用点自行决定。
http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      // 清除认证状态，触发 app store 的 authed watcher 统一处理跳转
      const store = useAppStore()
      store.token = ''
      localStorage.removeItem('flower_token')
    }
    return Promise.reject(err)
  }
)

export default http
