<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { proxyApi } from '@/api'
import { useNotify } from '@/components/ui'

const { triggerNotify } = useNotify()
const stats = ref<Record<string, number>>({})
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const fetchAll = async () => {
  try {
    const [st, r] = await Promise.all([proxyApi.stats(), proxyApi.list({ page: page.value, size: size.value })])
    stats.value = st as any; items.value = (r as any).items; total.value = (r as any).total
  } catch {}
}

const doFetch = async () => { try { await proxyApi.fetch(); triggerNotify('正在拉取 IP...', 'info'); setTimeout(fetchAll, 3000) } catch {} }
const doKill = async (id: number) => { try { await proxyApi.kill(id); triggerNotify('已淘汰', 'success'); fetchAll() } catch {} }
const doHealthCheck = async () => { try { await proxyApi.healthCheck(); triggerNotify('健康检查已触发', 'info') } catch {} }

const handlePageChange = (p: number) => { page.value = p; fetchAll() }
const handleSizeChange = (s: number) => { size.value = s; page.value = 1; fetchAll() }

const statusColors: Record<string, string> = {
  idle: 'status-label-done', in_use: 'status-label-running', cooldown: 'status-label-failed', dead: 'status-label-blocked',
}

onMounted(fetchAll)
</script>

<template>
  <div class="space-y-ax-md">
    <div class="grid grid-cols-4 gap-ax-sm">
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">池总数</div>
        <div class="text-2xl font-medium text-primary">{{ (stats.idle||0) + (stats.in_use||0) + (stats.cooldown||0) + (stats.dead||0) }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">可用 idle</div>
        <div class="text-2xl font-medium text-primary">{{ stats.idle || 0 }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">冷却中</div>
        <div class="text-2xl font-medium" style="color: #ba7517">{{ stats.cooldown || 0 }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">已淘汰</div>
        <div class="text-2xl font-medium" style="color: #a32d2d">{{ stats.dead || 0 }}</div>
      </div>
    </div>

    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm">
      <AxButton variant="primary"  size="lg" icon="add" @click="doFetch">手动拉取 10 个 IP</AxButton>
      <AxButton variant="outline"  size="lg" icon="monitor_heart" @click="doHealthCheck">立即健康检查</AxButton>
    </div>

    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-surface-container-low text-secondary text-[11px]">
          <tr>
            <th class="text-left px-4 py-2 font-medium">IP:Port</th>
            <th class="text-left px-4 py-2 font-medium w-14">城市</th>
            <th class="text-left px-4 py-2 font-medium w-16">状态</th>
            <th class="text-left px-4 py-2 font-medium w-16">使用</th>
            <th class="text-left px-4 py-2 font-medium w-16">失败</th>
            <th class="text-left px-4 py-2 font-medium w-28">过期时间</th>
            <th class="text-left px-4 py-2 font-medium w-16">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-outline-variant">
          <tr v-for="p in items" :key="p.id" class="hover:bg-surface-container-low">
            <td class="px-4 py-2 font-mono text-primary">{{ p.ip }}:{{ p.port }}</td>
            <td class="px-4 py-2 text-secondary">{{ p.city }}</td>
            <td class="px-4 py-2"><span class="pill" :class="statusColors[p.status] || ''">{{ p.status }}</span></td>
            <td class="px-4 py-2 text-secondary">{{ p.use }}/{{ p.max_use }}</td>
            <td class="px-4 py-2" :style="{ color: p.fail > 0 ? 'var(--color-text-error, #a32d2d)' : '' }">{{ p.fail }}</td>
            <td class="px-4 py-2 text-secondary text-[11px]">{{ p.expire_at || '-' }}</td>
            <td class="px-4 py-2"><AxButton variant="ghost"  size="lg" style="color:#a32d2d" @click="doKill(p.id)">淘汰</AxButton></td>
          </tr>
        </tbody>
      </table>
      <div class="px-4 py-ax-sm border-t border-outline-variant">
        <AxPagination
          :page="page"
          :size="size"
          :total="total"
          :sizes="[20, 50, 100]"
          @update:page="handlePageChange"
          @update:size="handleSizeChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.pill { padding: 1px 8px; border-radius: 999px; font-size: 10px; line-height: 1.6; }
.status-label-done { background: #e1f5ee; color: #085041; }
.status-label-running { background: #e6f1fb; color: #0c447c; }
.status-label-failed { background: #faeeda; color: #633806; }
.status-label-blocked { background: #fcebeb; color: #791f1f; }
</style>