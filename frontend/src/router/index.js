import { createRouter, createWebHashHistory } from 'vue-router'

import { useAppStore } from '@/stores/app'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, layout: 'blank' }
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '监控总览', icon: 'Odometer' }
  },
  {
    path: '/workers',
    name: 'workers',
    component: () => import('@/views/WorkersView.vue'),
    meta: { title: 'Workers', icon: 'Cpu' }
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('@/views/TasksView.vue'),
    meta: { title: '任务列表', icon: 'List' }
  },
  {
    path: '/broker',
    name: 'broker',
    component: () => import('@/views/BrokerView.vue'),
    meta: { title: 'Broker 队列', icon: 'Coordinate' }
  },
  {
    path: '/monitor',
    name: 'monitor',
    component: () => import('@/views/MonitorView.vue'),
    meta: { title: '实时图表', icon: 'TrendCharts' }
  },
  {
    path: '/apply',
    name: 'apply',
    component: () => import('@/views/ApplyTaskView.vue'),
    meta: { title: '下发任务', icon: 'Promotion' }
  },
  {
    path: '/config',
    name: 'config',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '系统配置', icon: 'Setting' }
  },
  {
    path: '/system',
    name: 'system',
    component: () => import('@/views/SystemView.vue'),
    meta: { title: '系统信息', icon: 'InfoFilled' }
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to) => {
  const store = useAppStore()
  if (store.authEnabled === false && !store._checked) {
    await store.loadAuthConfig()
    store._checked = true
  }
  if (!to.meta.public && store.authEnabled && !store.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && store.token) return { name: 'dashboard' }
  return true
})

export default router
export { routes }
