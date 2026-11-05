<template>
  <div class="dag-view">
    <div class="dag-header">
      <h2>DAG 视图</h2>
      <div class="dag-controls">
        <el-input
          v-model="searchQuery"
          placeholder="搜索任务..."
          clearable
          style="width: 240px"
          @input="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button @click="resetView">重置视图</el-button>
      </div>
    </div>
    
    <div ref="cyContainer" class="cy-container"></div>
    
    <el-empty v-if="!loading && nodes.length === 0" description="暂无任务数据" />
    
    <div class="dag-footer">
      <el-tag type="info">节点数: {{ nodes.length }}</el-tag>
      <el-tag type="success">边数: {{ edges.length }}</el-tag>
      <el-tag v-if="filteredNodes.length !== nodes.length" type="warning">
        过滤后: {{ filteredNodes.length }}
      </el-tag>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import cytoscape from 'cytoscape'
import { Search } from '@element-plus/icons-vue'
import { taskApi } from '@/api'

const cyContainer = ref(null)
const searchQuery = ref('')
const loading = ref(true)
const cyInstance = ref(null)

const nodes = ref([])
const edges = ref([])

const filteredNodes = computed(() => {
  if (!searchQuery.value) return nodes.value
  const query = searchQuery.value.toLowerCase()
  return nodes.value.filter(node => 
    node.name.toLowerCase().includes(query) || 
    node.id.toLowerCase().includes(query)
  )
})

const filteredEdges = computed(() => {
  if (!searchQuery.value) return edges.value
  const filteredIds = new Set(filteredNodes.value.map(n => n.id))
  return edges.value.filter(edge => 
    filteredIds.has(edge.source) && filteredIds.has(edge.target)
  )
})

async function fetchDagData() {
  try {
    loading.value = true
    const response = await fetch('/api/dag/tasks')
    const data = await response.json()
    nodes.value = (data.nodes || []).map(n => ({
      id: n.id,
      name: n.name,
      group: n.queue === 'system' ? 'system' : 'task'
    }))
    edges.value = (data.edges || []).map(e => ({
      source: e.source,
      target: e.target
    }))
  } catch (error) {
    console.error('获取 DAG 数据失败:', error)
  } finally {
    loading.value = false
  }
}

function initCytoscape() {
  if (!cyContainer.value) return
  
  cyInstance.value = cytoscape({
    container: cyContainer.value,
    elements: [...nodes.value, ...edges.value],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'linear-gradient(#6ECBF6, #278df3)',
          'label': 'data(name)',
          'width': 120,
          'height': 40,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': 110,
          'font-size': '12px',
          'color': '#fff',
          'shape': 'round-rectangle',
          'border-width': 2,
          'border-color': '#1a6cb8'
        }
      },
      {
        selector: 'node[group="system"]',
        style: {
          'background-color': 'linear-gradient(#a8e6cf, #56ab2f)',
          'border-color': '#3d8a24'
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 2,
          'line-color': '#ccc',
          'target-arrow-color': '#ccc',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier'
        }
      }
    ],
    layout: {
      name: 'breadthfirst',
      directed: true,
      padding: 20,
      fit: true,
      animate: true,
      animationDuration: 500
    },
    minZoom: 0.2,
    maxZoom: 3,
    zoomEnabled: true,
    userZoomingEnabled: true,
    panEnabled: true,
    userPanningEnabled: true,
    boxSelectionEnabled: true,
    selectionType: 'single'
  })

  // 点击节点高亮相关边
  cyInstance.value.on('tap', 'node', (evt) => {
    const node = evt.target
    cyInstance.value.elements('edge').style('opacity', 0.2)
    node.connectedEdges().style('opacity', 1)
    node.connectedNodes().style('opacity', 1)
    node.style('opacity', 1)
  })

  // 点击空白处重置
  cyInstance.value.on('tap', (evt) => {
    if (evt.target === cyInstance.value.container()) {
      cyInstance.value.elements().style('opacity', 1)
    }
  })
}

function handleSearch() {
  // 重新渲染过滤后的元素
  if (cyInstance.value) {
    cyInstance.value.elements().remove()
    cyInstance.value.add([...filteredNodes.value, ...filteredEdges.value])
    cyInstance.value.layout({
      name: 'breadthfirst',
      directed: true,
      padding: 20,
      fit: true,
      animate: true
    }).run()
  }
}

function resetView() {
  searchQuery.value = ''
  if (cyInstance.value) {
    cyInstance.value.elements().style('opacity', 1)
    cyInstance.value.fit()
    cyInstance.value.zoom(1)
  }
}

onMounted(async () => {
  await fetchDagData()
  initCytoscape()
})

onUnmounted(() => {
  if (cyInstance.value) {
    cyInstance.value.destroy()
    cyInstance.value = null
  }
})
</script>

<style scoped>
.dag-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;
  background: var(--el-bg-color);
}

.dag-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.dag-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.dag-controls {
  display: flex;
  gap: 12px;
  align-items: center;
}

.cy-container {
  flex: 1;
  min-height: 500px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-fill-color-light);
}

.dag-footer {
  margin-top: 12px;
  display: flex;
  gap: 12px;
}
</style>
