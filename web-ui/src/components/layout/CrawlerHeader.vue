<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { crawlerApi } from '@/api'
import { getSocket } from '@/api/ws'
import { useNotify } from '@/components/ui'

type CrawlerStatus = 'running' | 'paused' | 'stopped'

const route = useRoute()
const { triggerNotify } = useNotify()
const title = computed(() => (route.meta.title as string) || '')
const desc = computed(() => (route.meta.desc as string) || '')
const crawlerStatus = ref<CrawlerStatus>('stopped')
const loading = ref(false)

const isRunning = computed(() => crawlerStatus.value === 'running')
const btnText = computed(() => isRunning.value ? '暂停爬虫' : '启动爬虫')
const btnIcon = computed(() => isRunning.value ? 'pause' : 'play_arrow')

const doRefresh = () => { location.reload() }

const fetchStatus = async () => {
  try {
    const res = await crawlerApi.status()
    crawlerStatus.value = (res?.status as CrawlerStatus) || 'stopped'
  } catch { /* initial poll, silent */ }
}

const doToggleCrawler = async () => {
  if (loading.value) return
  loading.value = true
  try {
    if (isRunning.value) {
      await crawlerApi.pause()
      crawlerStatus.value = 'paused'
      triggerNotify('爬虫已暂停', 'info')
    } else {
      await crawlerApi.start()
      crawlerStatus.value = 'running'
      triggerNotify('爬虫已启动', 'success')
    }
  } catch { /* handled by socket event */ }
  finally { loading.value = false }
}

let s: ReturnType<typeof getSocket>
onMounted(async () => {
  await fetchStatus()
  s = getSocket()
  s.on('crawler_status', (data: { status: string }) => {
    crawlerStatus.value = (data.status as CrawlerStatus) || 'stopped'
  })
})

onBeforeUnmount(() => {
  s?.off('crawler_status')
})
</script>

<template>
  <header class="h-14 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-margin shrink-0">
    <div>
      <h1 class="text-base font-medium leading-tight text-primary">{{ title }}</h1>
      <div class="text-[11px] text-secondary leading-tight">{{ desc }}</div>
    </div>
    <div class="flex items-center gap-ax-sm">
      <AxButton variant="outline" size="lg" icon="refresh" @click="doRefresh">刷新</AxButton>
      <AxButton
        variant="primary"
        size="lg"
        :icon="btnIcon"
        :loading="loading"
        @click="doToggleCrawler"
      >{{ btnText }}</AxButton>
    </div>
  </header>
</template>