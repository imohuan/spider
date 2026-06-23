<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { captchaApi } from '@/api'
import { useLinkify } from '@/components/ui'

const { linkify } = useLinkify()

const cs = ref({ today: 0, auto_success: 0, switch_ip: 0, manual: 0 })
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)

const strategyColors: Record<string, string> = { auto: 'badge-auto', switch_ip: 'badge-switch', manual: 'badge-manual' }
const resultColors: Record<string, string> = { success: 'badge-ok', switched_ip: 'badge-switch', manual: 'badge-manual', failed: 'badge-err' }

const fetchAll = async () => {
  try {
    const [s, r] = await Promise.all([captchaApi.stats(), captchaApi.list({ page: page.value, size: 20 })])
    cs.value = s as any; items.value = (r as any).items; total.value = (r as any).total
  } catch {}
}

onMounted(fetchAll)
</script>

<template>
  <div class="space-y-ax-md">
    <div class="grid grid-cols-4 gap-ax-sm">
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">今日触发</div>
        <div class="text-2xl font-medium text-primary">{{ cs.today }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">自动通过</div>
        <div class="text-2xl font-medium" style="color: #1d9e75">{{ cs.auto_success }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">换IP通过</div>
        <div class="text-2xl font-medium" style="color: #534ab7">{{ cs.switch_ip }}</div>
      </div>
      <div class="bg-surface-container-lowest border border-outline-variant rounded-xl p-ax-md">
        <div class="text-xs text-secondary">转人工</div>
        <div class="text-2xl font-medium" style="color: #a32d2d">{{ cs.manual }}</div>
      </div>
    </div>

    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-surface-container-low text-secondary text-[11px]">
          <tr>
            <th class="text-left px-4 py-2 font-medium w-32">时间</th>
            <th class="text-left px-4 py-2 font-medium">URL</th>
            <th class="text-left px-4 py-2 font-medium w-48">IP</th>
            <th class="text-left px-4 py-2 font-medium w-32">策略</th>
            <th class="text-left px-4 py-2 font-medium w-32">尝试</th>
            <th class="text-left px-4 py-2 font-medium w-32">结果</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-outline-variant">
          <tr v-for="c in items" :key="c.id" class="hover:bg-surface-container-low">
            <td class="px-4 py-2 text-secondary text-[11px]">{{ c.triggered_at }}</td>
            <td class="px-4 py-2 font-mono truncate max-w-xs" v-html="linkify(c.url)" />
            <td class="px-4 py-2 font-mono text-secondary">{{ c.ip }}</td>
            <td class="px-4 py-2"><span class="pill" :class="strategyColors[c.strategy] || ''">{{ c.strategy }}</span></td>
            <td class="px-4 py-2 text-secondary">{{ c.attempt }}</td>
            <td class="px-4 py-2"><span class="pill" :class="resultColors[c.result] || ''">{{ c.result }}</span></td>
          </tr>
        </tbody>
      </table>
      </div>
      <div class="px-4 py-ax-sm border-t border-outline-variant flex justify-between text-[11px] text-secondary">
        <span>{{ total }} 条</span>
        <div class="flex gap-ax-sm">
          <AxButton variant="ghost"  size="lg" :disabled="page<=1" @click="page--;fetchAll()">上一页</AxButton>
          <AxButton variant="ghost"  size="lg" :disabled="page>=Math.ceil(total/20)||total===0" @click="page++;fetchAll()">下一页</AxButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pill { padding: 1px 8px; border-radius: 999px; font-size: 10px; line-height: 1.6; }
.badge-auto { background: #e6f1fb; color: #0c447c; }
.badge-switch { background: #eeedfe; color: #3c3489; }
.badge-manual { background: #faeeda; color: #633806; }
.badge-ok { background: #e1f5ee; color: #085041; }
.badge-err { background: #fcebeb; color: #791f1f; }
</style>