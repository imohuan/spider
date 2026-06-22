<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import { getSocket } from '@/api/ws'
import { logsApi } from '@/api'

const logContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const filterLevel = ref<string[]>([])
const filterSearch = ref('')
const connected = ref(false)

const historicalLines = ref<string[]>([])
const wsLogs = ref<Array<{ level: string; module: string; message: string; timestamp: string }>>([])

const levelColors: Record<string, string> = { INFO: '#1e7b5a', WARNING: '#b86e00', ERROR: '#c42b2b', DEBUG: '#6b6a65' }

function parseLine(line: string) {
  const m = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.+?)\s+-\s+(.+)$/)
  if (m) return { timestamp: m[1], level: m[2], module: m[3], message: m[4] }
  // 裸文本（werkzeug banner / traceback）: 不带 level，不过滤
  return { timestamp: '', level: '', module: '', message: line }
}

const displayLogs = computed(() => {
  const hist = historicalLines.value.map(parseLine)
  return [...hist, ...wsLogs.value]
})

const filteredLogs = computed(() => {
  return displayLogs.value.filter(l => {
    if (filterLevel.value.length && l.level && !filterLevel.value.includes(l.level)) return false
    if (filterSearch.value) {
      const s = filterSearch.value.toLowerCase()
      if (!l.message.toLowerCase().includes(s) && !l.module.toLowerCase().includes(s)) return false
    }
    return true
  })
})

async function loadHistoricalLogs() {
  try {
    const res: any = await logsApi.getAll()
    historicalLines.value = (res.items || []).reverse()
  } catch (e) {
    console.error('Failed to load historical logs:', e)
  }
}

function clearLogs() {
  historicalLines.value = []
  wsLogs.value = []
}

watch(filteredLogs, () => {
  if (autoScroll.value) {
    nextTick(() => {
      if (logContainer.value) logContainer.value.scrollTop = logContainer.value.scrollHeight
    })
  }
})

let socket: ReturnType<typeof getSocket> | null = null
onMounted(() => {
  loadHistoricalLogs()
  socket = getSocket()
  if (socket.connected) connected.value = true
  socket.on('connect', () => { connected.value = true })
  socket.on('disconnect', () => { connected.value = false })
  socket.on('log', (data: any) => {
    wsLogs.value.push(data)
    if (wsLogs.value.length > 2000) wsLogs.value.shift()
  })
})

onBeforeUnmount(() => {
  socket?.off('connect')
  socket?.off('disconnect')
  socket?.off('log')
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0 select-none">
    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm flex-shrink-0 mb-ax-md">
      <span class="text-xs text-secondary flex-shrink-0">级别</span>
      <label class="text-xs flex items-center gap-1 flex-shrink-0 cursor-pointer">
        <input type="checkbox" v-model="filterLevel" value="INFO" class="accent-primary"> INFO
      </label>
      <label class="text-xs flex items-center gap-1 flex-shrink-0 cursor-pointer">
        <input type="checkbox" v-model="filterLevel" value="DEBUG" class="accent-primary"> DEBUG
      </label>
      <label class="text-xs flex items-center gap-1 flex-shrink-0 cursor-pointer">
        <input type="checkbox" v-model="filterLevel" value="WARNING" class="accent-primary"> WARN
      </label>
      <label class="text-xs flex items-center gap-1 flex-shrink-0 cursor-pointer">
        <input type="checkbox" v-model="filterLevel" value="ERROR" class="accent-primary"> ERROR
      </label>
      <AxInput v-model="filterSearch" size="lg" placeholder="搜索..." class="flex-1 min-w-0 ml-2" />
      <label class="text-xs flex items-center gap-1 flex-shrink-0 cursor-pointer">
        <input type="checkbox" v-model="autoScroll" class="accent-primary"> 自动滚动
      </label>
      <AxButton variant="outline" size="lg" @click="clearLogs" class="flex-shrink-0">清空</AxButton>
    </div>

    <div ref="logContainer" class="select-text flex-1 min-h-0 bg-surface-container-low border border-outline-variant rounded-xl p-ax-md text-xs leading-relaxed overflow-y-auto">
      <template v-for="(l, i) in filteredLogs" :key="i">
        <div v-if="!l.level" class="text-tertiary break-all whitespace-pre-wrap pl-[60px]" :class="i > 0 ? 'mt-0.5' : ''">{{ l.message }}</div>
        <div v-else class="flex items-baseline gap-ax-sm" :class="i > 0 ? 'mt-0.5' : ''">
          <span class="text-tertiary flex-shrink-0 font-mono">{{ l.timestamp }}</span>
          <span class="flex-shrink-0 font-semibold font-mono" :style="{ color: levelColors[l.level] || '#888' }">[{{ l.level }}]</span>
          <span class="text-secondary flex-shrink-0 font-mono truncate max-w-[140px]">{{ l.module }}</span>
          <span class="text-primary flex-1 break-all">{{ l.message }}</span>
        </div>
      </template>
      <div v-if="!connected" class="text-error">WebSocket 未连接 — 等待连接中...</div>
      <div v-else-if="filteredLogs.length === 0 && filterSearch" class="text-secondary">无匹配结果</div>
      <div v-else-if="filteredLogs.length === 0" class="text-secondary">暂无日志</div>
    </div>
  </div>
</template>
