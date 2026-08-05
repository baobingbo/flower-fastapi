<script setup>
import { computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { useAppStore } from '@/stores/app'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const settings = useSettingsStore()
const theme = useThemeStore()

const blank = computed(() => route.meta.layout === 'blank')
const transitionName = computed(() => (settings.pageTransition ? 'fu-fade' : ''))

onMounted(async () => {
  // 主题优先初始化，避免首屏闪白
  theme.init()

  // 服务端界面默认值（主题 / 通道 / 轮询间隔）——仅在本地未设置过时生效
  const ui = await store.loadUiDefaults()
  if (ui?.theme && !localStorage.getItem('flower_theme')) {
    theme.setPreference(ui.theme)
  }

  await store.loadAuthConfig()
  if (store.authed) {
    store.connect()
    store.loadFilters()
  }
})

watch(
  () => store.authed,
  (ok) => {
    if (ok) {
      store.connect()
      store.loadFilters()
    } else {
      store.disconnect()
      // 同样使用 router.push 而非 location.hash
      if (!route.path.startsWith('/login')) {
        router.push({ name: 'login', query: { redirect: route.fullPath } })
      }
    }
  }
)

onBeforeUnmount(() => store.disconnect())
</script>

<template>
  <router-view v-if="blank" />
  <AppLayout v-else>
    <router-view v-slot="{ Component }">
      <transition :name="transitionName" mode="out-in">
        <keep-alive :include="['TasksView']">
          <component :is="Component" />
        </keep-alive>
      </transition>
    </router-view>
  </AppLayout>
</template>

<style>
.fu-fade-enter-active,
.fu-fade-leave-active {
  transition: opacity var(--fu-duration) var(--fu-ease),
    transform var(--fu-duration) var(--fu-ease);
}

.fu-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.fu-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
