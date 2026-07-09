<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import { getSocket } from '@/api/ws'
import { logsApi } from '@/api'

const PAGE_SIZE = 5000

const logContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const filterLevel = ref<string[]>([])
const filterSearch = ref('')
const connected = ref(false)

// 历史日志分页
const pages = ref<string[][]>([])   // pages[0] = 第1页（最新）
const currentPage = ref(0)
const hasMore = ref(true)
const loading = ref(false)

// WebSocket 实时日志
const wsLogs = ref<Array<{ level: string; module: string; message: string; timestamp: string }>>([])

const levelColors: Record<string, string> = {
  INFO: '#1e7b5a',
  WARNING: '#b86e00',
  ERROR: '#c42b2b',
  DEBUG: '#6b6a65',
}

function parseLine(line: string) {
  const m = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.+?)\s+-\s+(.+)$/)
  if (m) return { timestamp: m[1], level: m[2], module: m[3], message: m[4] }
  // 裸文本（traceback / werkzeug banner / 多行续行）
  return { timestamp: '', level: '_raw', module: '', message: line }
}

const displayLogs = computed(() => {
  const all: ReturnType<typeof parseLine>[] = []
  // 按页倒序拼接：pages[0] 最新, pages[N] 最旧，但数组内每页已经是倒序的
  // 渲染时需要时间从新到旧，所以遍历 pages 时用 concat（保持每个 page 内部顺序不变）
  for (let i = currentPage.value; i >= 0; i--) {
    if (pages.value[i]) {
      all.push(...pages.value[i].map(parseLine))
    }
  }
  // WS 实时日志追加在最新日志后面
  return [...all, ...wsLogs.value]
})

const filteredLogs = computed(() => {
  return displayLogs.value.filter(l => {
    // 裸文本行始终显示（不过滤），除非有搜索关键词
    if (l.level === '_raw') {
      if (filterSearch.value) {
        return l.message.toLowerCase().includes(filterSearch.value.toLowerCase())
      }
      return true
    }
    if (filterLevel.value.length && l.level && !filterLevel.value.includes(l.level)) return false
    if (filterSearch.value) {
      const s = filterSearch.value.toLowerCase()
      if (!l.message.toLowerCase().includes(s) && !l.module.toLowerCase().includes(s)) return false
    }
    return true
  })
})

async function loadPage(page: number) {
  if (loading.value) return
  loading.value = true
  try {
    const res: any = await logsApi.getPage({ page: page + 1, size: PAGE_SIZE })
    const items: string[] = res.items || []
    if (items.length > 0) {
      pages.value[page] = items
      currentPage.value = Math.max(currentPage.value, page)
    }
    hasMore.value = res.has_more ?? false
  } catch (e) {
    console.error('加载日志失败:', e)
  } finally {
    loading.value = false
  }
}

// 处理滚动：滚到顶部时加载更早的日志
function onScroll() {
  const el = logContainer.value
  if (!el || loading.value || !hasMore.value) return

  // 距离顶部小于 50px 时加载下一页（更早的日志）
  if (el.scrollTop < 50) {
    const prevHeight = el.scrollHeight
    loadPage(currentPage.value + 1).then(() => {
      nextTick(() => {
        if (logContainer.value) {
          // 保持滚动位置不跳动
          logContainer.value.scrollTop = logContainer.value.scrollHeight - prevHeight
        }
      })
    })
  }
}

async function loadHistoricalLogs() {
  await loadPage(0)
  // 初始加载后滚动到底部
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

function clearLogs() {
  pages.value = []
  currentPage.value = 0
  hasMore.value = true
  wsLogs.value = []
}

// WS 新日志来了自动滚到底部
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

    <div
      ref="logContainer"
      class="select-text flex-1 min-h-0 bg-surface-container-low border border-outline-variant rounded-xl p-ax-md text-xs leading-relaxed overflow-y-auto"
      @scroll="onScroll"
    >
      <!-- 顶部加载提示 -->
      <div v-if="loading" class="text-center text-tertiary py-2">加载中...</div>
      <div v-else-if="hasMore" class="text-center text-tertiary py-2 text-[11px]">↑ 滚动到顶部加载更多</div>
      <div v-else class="text-center text-tertiary py-2 text-[11px]">—— 已加载全部日志 ——</div>

      <template v-for="(l, i) in filteredLogs" :key="i">
        <div v-if="l.level === '_raw'" class="text-tertiary break-all whitespace-pre-wrap pl-[60px]" :class="i > 0 ? 'mt-0.5' : ''">{{ l.message }}</div>
        <div v-else class="flex items-baseline gap-ax-sm" :class="i > 0 ? 'mt-0.5' : ''">
          <span class="text-tertiary flex-shrink-0 font-mono">{{ l.timestamp }}</span>
          <span class="flex-shrink-0 font-semibold font-mono" :style="{ color: levelColors[l.level] || '#888' }">[{{ l.level }}]</span>
          <span class="text-secondary flex-shrink-0 font-mono truncate max-w-[140px]">{{ l.module }}</span>
          <span class="text-primary flex-1 break-all">{{ l.message }}</span>
        </div>
      </template>

      <div v-if="!connected" class="text-error">WebSocket 未连接 — 等待连接中...</div>
      <div v-else-if="filteredLogs.length === 0 && filterSearch" class="text-secondary">无匹配结果</div>
      <div v-else-if="filteredLogs.length === 0 && !loading" class="text-secondary">暂无日志</div>
    </div>
  </div>
</template>