<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ThemeSwitcher from '@/components/ThemeSwitcher.vue'
import DetailOverlay from '@/components/DetailOverlay.vue'
import { routes } from '@/router'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'
import { fmtUptime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const settings = useSettingsStore()

const menus = computed(() =>
  routes.filter((r) => r.meta?.title && !r.meta.hidden && !r.meta.public)
)

/** 详情已改为悬浮抽屉，不再有独立路由，侧边栏始终按当前列表页高亮 */
const activeMenu = computed(() => route.path)

const collapsed = computed(() => settings.sidebarCollapsed)
const asideWidth = computed(() => (collapsed.value ? '64px' : '216px'))

const connText = computed(() => {
  if (!store.connected) return '连接已断开'
  return settings.transport === 'polling' ? '轮询中' : '实时连接正常'
})

function logout() {
  store.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container class="fu-shell">
    <el-aside :width="asideWidth" class="fu-aside" :class="{ collapsed }">
      <div class="brand" :class="{ collapsed }">
        <span class="brand-logo">🌸</span>
        <div v-show="!collapsed" class="brand-text">
          <div class="brand-name">FlowerUI</div>
          <div class="brand-sub">Celery 实时监控</div>
        </div>
      </div>

      <el-scrollbar class="menu-wrap">
        <el-menu
          :default-active="activeMenu"
          :collapse="collapsed"
          :collapse-transition="false"
          router
          class="fu-menu"
        >
          <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
            <el-icon><component :is="m.meta.icon" /></el-icon>
            <template #title>{{ m.meta.title }}</template>
          </el-menu-item>
        </el-menu>
      </el-scrollbar>

      <div class="aside-foot" :class="{ collapsed }">
        <el-tooltip
          :content="`${connText} · ${store.transportLabel}`"
          placement="right"
          :disabled="!collapsed"
        >
          <div class="conn">
            <span class="dot" :class="store.connected ? 'on' : 'off'" />
            <span v-show="!collapsed">{{ connText }}</span>
          </div>
        </el-tooltip>
        <div v-show="!collapsed" class="text-muted foot-uptime">
          运行 {{ fmtUptime(store.summary.uptime) }}
        </div>
      </div>
    </el-aside>

    <el-container class="fu-body">
      <el-header class="fu-header">
        <div class="header-left">
          <el-tooltip :content="collapsed ? '展开导航' : '收起导航'" placement="bottom">
            <button class="icon-btn" @click="settings.toggleSidebar()">
              <el-icon :size="17">
                <component :is="collapsed ? 'Expand' : 'Fold'" />
              </el-icon>
            </button>
          </el-tooltip>

          <span class="header-title">{{ route.meta?.title || '监控总览' }}</span>

          <el-tag v-if="store.mockMode" type="warning" size="small" effect="light" round>
            演示模式
          </el-tag>
          <el-tag v-else type="success" size="small" effect="light" round>
            {{ store.summary.transport || 'broker' }}
          </el-tag>
        </div>

        <div class="header-right">
          <el-tooltip :content="store.summary.broker_url || ''" placement="bottom">
            <span class="mono text-muted broker-url">{{ store.summary.broker_url }}</span>
          </el-tooltip>

          <el-tooltip
            :content="`数据通道：${store.transportLabel}（可在配置页切换）`"
            placement="bottom"
          >
            <span class="chan" :class="{ off: !store.connected }" @click="router.push('/config')">
              <el-icon :size="14">
                <component :is="settings.transport === 'polling' ? 'Refresh' : 'Link'" />
              </el-icon>
              {{ settings.transport === 'polling' ? `轮询 ${settings.pollInterval}ms` : '实时' }}
            </span>
          </el-tooltip>

          <el-badge :value="store.summary.workers_online || 0" type="success" class="badge">
            <el-button text size="small" @click="router.push('/workers')">
              <el-icon><Cpu /></el-icon>&nbsp;Workers
            </el-button>
          </el-badge>

          <ThemeSwitcher />

          <el-dropdown v-if="store.authEnabled" @command="logout">
            <span class="user">
              <el-icon><UserFilled /></el-icon>&nbsp;{{ store.user || '未登录' }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>&nbsp;退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span v-else class="text-muted no-auth">未启用鉴权</span>
        </div>
      </el-header>

      <el-main class="fu-main">
        <slot />
      </el-main>
    </el-container>

    <DetailOverlay />
  </el-container>
</template>

<style scoped>
.fu-shell {
  height: 100%;
}

/* ---------------- 侧边栏 ---------------- */
.fu-aside {
  background-color: var(--fu-surface);
  background-image: var(--fu-aside-bg-image);
  border-right: 1px solid var(--fu-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--fu-duration) var(--fu-ease);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px 14px;
  border-bottom: 1px solid var(--fu-border);
  white-space: nowrap;
  min-height: 62px;
}

.brand.collapsed {
  padding: 16px 0 14px;
  justify-content: center;
}

.brand-logo {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.brand-name {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.2px;
  color: var(--fu-text);
}

.brand-sub {
  font-size: 11.5px;
  color: var(--fu-text-muted);
}

.menu-wrap {
  flex: 1;
  min-height: 0;
}

.fu-menu {
  border-right: none;
  padding-top: 6px;
  background: transparent;
}

.fu-menu:not(.el-menu--collapse) {
  width: 100%;
}

.aside-foot {
  padding: 12px 18px 16px;
  border-top: 1px solid var(--fu-border);
}

.aside-foot.collapsed {
  padding: 12px 0 16px;
  text-align: center;
}

.conn {
  font-size: 12.5px;
  color: var(--fu-text-muted);
  display: flex;
  align-items: center;
  justify-content: inherit;
}

.aside-foot.collapsed .conn {
  justify-content: center;
}

.aside-foot.collapsed .conn .dot {
  margin-right: 0;
}

.foot-uptime {
  font-size: 11.5px;
  margin-top: 4px;
}

/* ---------------- 头部 ---------------- */
.fu-header {
  background-color: var(--fu-surface);
  background-image: var(--fu-aside-bg-image);
  border-bottom: 1px solid var(--fu-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--fu-header-height);
  padding: 0 16px 0 10px;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.header-title {
  font-size: var(--fu-font-size-md);
  font-weight: 640;
  color: var(--fu-text);
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--fu-radius-sm);
  background: transparent;
  color: var(--fu-text-secondary);
  cursor: pointer;
  transition: var(--fu-transition);
}

.icon-btn:hover {
  background: var(--fu-brand-soft);
  color: var(--fu-brand);
}

.broker-url {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}

.chan {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 3px 9px;
  border-radius: var(--fu-radius-pill);
  background: var(--fu-success-soft);
  color: var(--fu-success);
  cursor: pointer;
  white-space: nowrap;
  transition: var(--fu-transition);
}

.chan:hover {
  filter: brightness(1.08);
}

.chan.off {
  background: var(--fu-danger-soft);
  color: var(--fu-danger);
}

.user {
  cursor: pointer;
  font-size: 13px;
  display: flex;
  align-items: center;
  color: var(--fu-text-secondary);
  outline: none;
}

.no-auth {
  font-size: 12.5px;
  white-space: nowrap;
}

/* ---------------- 主体 ---------------- */
.fu-main {
  padding: 0;
  background: transparent;
  overflow: auto;
}

@media (max-width: 900px) {
  .broker-url,
  .badge {
    display: none;
  }
}
</style>
