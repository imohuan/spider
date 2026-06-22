<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { dashboardApi } from '@/api'

const metrics = ref({ today_crawled: 0, success_rate: 0, queue_length: 0, ip_available: 0, ip_total: 0 })
const progress = ref<Array<{ hour: string; success: number; failed: number }>>([])
const recentFlows = ref<Array<{ url: string; parser: string; status: string; finished_at: string }>>([])

let timer: ReturnType<typeof setInterval>

const fetchAll = async () => {
  try {
    const [m, p, r] = await Promise.all([
      dashboardApi.getMetrics().catch(() => null),
      dashboardApi.getProgress().catch(() => []),
      dashboardApi.getRecent(10).catch(() => []),
    ])
    if (m) metrics.value = m as any
    if (p) progress.value = p as any
    if (r) recentFlows.value = r as any
  } catch {}
}

onMounted(() => { fetchAll(); timer = setInterval(fetchAll, 5000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="space-y-ax-md">
    <!-- 指标卡 -->
    <div class="grid grid-cols-4 gap-ax-sm">
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary mb-1">今日抓取</div>
        <div class="text-2xl font-medium text-primary">{{ metrics.today_crawled.toLocaleString() }}</div>
        <div class="text-[11px] text-secondary mt-1">{{ metrics.queue_length }} 个待处理</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary mb-1">成功率</div>
        <div class="text-2xl font-medium text-primary">{{ metrics.success_rate }}%</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary mb-1">队列长度</div>
        <div class="text-2xl font-medium text-primary">{{ metrics.queue_length }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary mb-1">IP 池可用</div>
        <div class="text-2xl font-medium text-primary">{{ metrics.ip_available }} <span class="text-sm text-secondary">/ {{ metrics.ip_total }}</span></div>
      </div>
    </div>

    <!-- 进度 + 流水 -->
    <div class="grid grid-cols-3 gap-ax-sm">
      <div class="col-span-2 bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="flex justify-between mb-3">
          <span class="text-sm font-medium text-primary">抓取进度（按小时）</span>
          <span class="text-[11px] text-secondary">最近 24h</span>
        </div>
        <div class="h-32 flex items-end gap-[3px]">
          <div v-for="(p, i) in progress.slice(-24)" :key="i"
            class="flex-1 rounded-t-sm bg-primary min-h-[2px]"
            :style="{ height: Math.max(2, p.success / Math.max(...progress.map(x => x.success || 1)) * 96) + 'px', opacity: 0.3 + (p.success / Math.max(...progress.map(x => x.success || 1)) * 0.7) }"></div>
        </div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="flex justify-between mb-3">
          <span class="text-sm font-medium text-primary">最近任务流水</span>
        </div>
        <div class="space-y-ax-sm text-xs max-h-48 overflow-y-auto">
          <div v-for="(f, i) in recentFlows.slice(0, 8)" :key="i" class="flex gap-ax-xs items-start">
            <span class="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0"
              :class="f.status === 'done' ? 'bg-primary' : f.status === 'failed' ? 'bg-error' : 'bg-warning'"></span>
            <div class="min-w-0 flex-1">
              <div class="font-medium truncate text-primary">{{ f.parser }} · {{ f.url }}</div>
              <div class="text-secondary text-[11px]">{{ f.status }}{{ f.finished_at ? ' · ' + f.finished_at : '' }}</div>
            </div>
          </div>
          <div v-if="recentFlows.length === 0" class="text-center text-secondary py-4">暂无数据</div>
        </div>
      </div>
    </div>
  </div>
</template>