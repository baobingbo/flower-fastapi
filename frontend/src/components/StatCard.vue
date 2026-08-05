<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  icon: { type: String, default: 'DataLine' },
  color: { type: String, default: '#409eff' },
  suffix: { type: String, default: '' },
  hint: { type: String, default: '' }
})
</script>

<template>
  <div class="stat-card">
    <div class="stat-icon" :style="{ background: color + '1a', color }">
      <el-icon :size="18"><component :is="icon" /></el-icon>
    </div>
    <div class="stat-body">
      <div class="stat-label">{{ label }}</div>
      <div class="stat-value" :style="{ color }">
        {{ value }}<span v-if="suffix" class="stat-suffix">{{ suffix }}</span>
      </div>
      <div v-if="hint" class="stat-hint">{{ hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  background: var(--fu-card);
  border: 1px solid var(--fu-border);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  height: 100%;
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(31, 45, 61, 0.08);
  transform: translateY(-1px);
}

.stat-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-body {
  min-width: 0;
  flex: 1;
}

.stat-label {
  font-size: 12.5px;
  color: var(--fu-text-muted);
  line-height: 1.2;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
}

.stat-suffix {
  font-size: 13px;
  font-weight: 500;
  margin-left: 3px;
  opacity: 0.75;
}

.stat-hint {
  font-size: 11.5px;
  color: var(--fu-text-muted);
}
</style>
