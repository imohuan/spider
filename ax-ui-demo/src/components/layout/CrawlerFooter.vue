<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { getSocket } from '@/api/ws'

const connected = ref(false)
const latency = ref(23)

let s: ReturnType<typeof getSocket>
onMounted(() => {
  s = getSocket()
  s.on('connect', () => { connected.value = true })
  s.on('disconnect', () => { connected.value = false })
})

onBeforeUnmount(() => {
  s?.off('connect'); s?.off('disconnect')
})
</script>

<template>
  <footer class="h-7 bg-surface-container-lowest border-t border-outline-variant flex items-center px-4 text-[10px] text-secondary gap-4 shrink-0 select-none">
    <span>WebSocket:
      <span :class="connected ? 'text-primary' : 'text-error'">{{ connected ? '已连接' : '未连接' }}</span>
    </span>
    <span>延迟: {{ latency }}ms</span>
    <span>最后同步: 2 秒前</span>
    <span class="ml-auto">58 爬虫管理后台 · 仅本机 127.0.0.1</span>
  </footer>
</template>