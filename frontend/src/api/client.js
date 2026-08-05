import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'

const http = axios.create({ baseURL: '/', timeout: 30000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('flower_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    const detail = err.response?.data?.detail || err.message
    if (status === 401) {
      // 清除认证状态，触发 app store 的 authed watcher 统一处理跳转
      const store = useAppStore()
      store.token = ''
      localStorage.removeItem('flower_token')
      // 静默请求或已在登录页时，不跳转
      if (!location.hash.includes('/login') && !err.config?.silent) {
        // authed watcher 会自动处理 router.push
      }
    } else if (!err.config?.silent) {
      ElMessage.error(typeof detail === 'string' ? detail : '请求失败')
    }
    return Promise.reject(err)
  }
)

export default http
