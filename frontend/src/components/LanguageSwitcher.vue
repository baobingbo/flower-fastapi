<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { locale } = useI18n()
const currentLang = computed(() => locale.value)

function switchLang(lang) {
  locale.value = lang
  localStorage.setItem('flower_lang', lang)
}
</script>

<template>
  <el-dropdown @command="switchLang">
    <span class="lang-switcher">
      <el-icon><Language /></el-icon>
      {{ currentLang === 'zh' ? '中文' : 'EN' }}
    </span>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="zh">中文</el-dropdown-item>
        <el-dropdown-item command="en">English</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.lang-switcher {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}
.lang-switcher:hover {
  background: var(--fu-brand-soft);
  color: var(--fu-brand);
}
</style>
