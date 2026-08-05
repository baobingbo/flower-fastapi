<script setup>
import { computed } from 'vue'

import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** compact = 只显示图标，用于折叠侧边栏/登录页 */
  compact: { type: Boolean, default: false }
})

const theme = useThemeStore()

const label = computed(() =>
  theme.isAuto ? `跟随系统 · ${theme.active.name}` : theme.active.name
)

function pick(command) {
  theme.setPreference(command)
}
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-end" @command="pick">
    <span class="ts-trigger" :class="{ compact: props.compact }">
      <el-icon :size="16">
        <component :is="theme.isDark ? 'Moon' : 'Sunny'" />
      </el-icon>
      <span v-if="!props.compact" class="ts-label">{{ label }}</span>
      <el-icon v-if="!props.compact" :size="12" class="ts-caret"><ArrowDown /></el-icon>
    </span>

    <template #dropdown>
      <el-dropdown-menu class="ts-menu">
        <div class="ts-section">外观</div>

        <el-dropdown-item command="auto" :class="{ picked: theme.isAuto }">
          <span class="ts-item">
            <el-icon :size="15"><Monitor /></el-icon>
            <span class="ts-name">跟随系统</span>
            <span class="ts-hint">当前 {{ theme.systemDark ? '深色' : '浅色' }}</span>
            <el-icon v-if="theme.isAuto" class="ts-check" :size="14"><Check /></el-icon>
          </span>
        </el-dropdown-item>

        <div class="ts-section">主题</div>

        <el-dropdown-item
          v-for="t in theme.themes"
          :key="t.id"
          :command="t.id"
          :class="{ picked: !theme.isAuto && theme.activeId === t.id }"
        >
          <span class="ts-item">
            <span class="ts-swatch">
              <i v-for="(c, i) in t.swatch" :key="i" :style="{ background: c }" />
            </span>
            <span class="ts-name">{{ t.name }}</span>
            <span class="ts-hint">{{ t.desc }}</span>
            <el-icon
              v-if="!theme.isAuto && theme.activeId === t.id"
              class="ts-check"
              :size="14"
            >
              <Check />
            </el-icon>
          </span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.ts-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 5px 9px;
  border-radius: var(--fu-radius-sm);
  color: var(--fu-text-secondary);
  font-size: 12.5px;
  border: 1px solid transparent;
  transition: var(--fu-transition);
  outline: none;
}

.ts-trigger:hover {
  background: var(--fu-brand-soft);
  border-color: var(--fu-border);
  color: var(--fu-brand);
}

.ts-trigger.compact {
  padding: 6px;
}

.ts-label {
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ts-caret {
  opacity: 0.6;
}
</style>

<style>
/* dropdown 挂在 body 上，必须用非 scoped 样式 */
.ts-menu {
  min-width: 268px;
  padding: 6px;
}

.ts-menu .ts-section {
  font-size: 11px;
  color: var(--fu-text-muted);
  padding: 6px 10px 4px;
  letter-spacing: 0.4px;
}

.ts-menu .el-dropdown-menu__item {
  border-radius: var(--fu-radius-sm);
  padding: 7px 10px;
  line-height: 1.4;
}

.ts-menu .el-dropdown-menu__item.picked {
  background: var(--fu-brand-soft);
  color: var(--fu-brand);
}

.ts-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  grid-template-areas: 'icon name check' 'icon hint check';
  align-items: center;
  gap: 0 10px;
  width: 100%;
}

.ts-item > .el-icon:first-child,
.ts-swatch {
  grid-area: icon;
}

.ts-name {
  grid-area: name;
  font-size: 13px;
  font-weight: 560;
}

.ts-hint {
  grid-area: hint;
  font-size: 11px;
  color: var(--fu-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 190px;
}

.ts-check {
  grid-area: check;
  color: var(--fu-brand);
}

.ts-swatch {
  display: inline-flex;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  overflow: hidden;
  border: 1px solid var(--fu-border);
  flex-shrink: 0;
}

.ts-swatch i {
  flex: 1;
}
</style>
