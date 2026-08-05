<script setup>
import { computed } from 'vue'

import { TASK_STATE_TYPE } from '@/utils/format'

const props = defineProps({
  state: { type: String, default: '' },
  size: { type: String, default: 'small' }
})

const type = computed(() => TASK_STATE_TYPE[props.state] || 'info')
</script>

<template>
  <el-tag :type="type" :size="size" effect="light" disable-transitions>
    {{ state || '-' }}
  </el-tag>
</template>
