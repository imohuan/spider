<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dataApi } from '@/api'

const tables = ref<Array<{ name: string; rows: number }>>([])
const selectedTable = ref('')
const rows = ref<any[]>([])
const columns = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const size = 20

const tableOptions = computed(() => tables.value.map(t => ({ value: t.name, label: `${t.name} (${t.rows} 行)` })))

const fetchTables = async () => {
  try { tables.value = await dataApi.tables() } catch {}
}

const fetchData = async () => {
  if (!selectedTable.value) return
  try {
    const r: any = await dataApi.query(selectedTable.value, { page: page.value, size })
    columns.value = r.columns; rows.value = r.items; total.value = r.total
  } catch {}
}

const onTableChange = (_name: string) => { page.value = 1; fetchData() }

const exportCsv = () => {
  if (selectedTable.value) window.open(dataApi.exportUrl(selectedTable.value))
}

onMounted(fetchTables)
</script>

<template>
  <div class="space-y-ax-md">
    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl px-4 py-ax-sm flex items-center gap-ax-sm">
      <span class="text-xs text-secondary">业务表</span>
      <AxSelect v-model="selectedTable" size="lg" :options="tableOptions" placeholder="请选择" @update:model-value="onTableChange" />
      <div class="flex-1"></div>
      <AxButton variant="outline"  size="lg" icon="download" @click="exportCsv" :disabled="!selectedTable">导出 CSV</AxButton>
    </div>

    <div class="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <table v-if="selectedTable && rows.length" class="w-full text-xs">
        <thead class="bg-surface-container-low text-secondary text-[11px]">
          <tr>
            <th v-for="c in columns" :key="c" class="text-left px-4 py-2 font-medium truncate">{{ c }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-outline-variant">
          <tr v-for="(r, i) in rows" :key="i" class="hover:bg-surface-container-low">
            <td v-for="c in columns" :key="c" class="px-4 py-2 text-primary truncate max-w-[200px]">{{ r[c] }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="p-ax-lg text-center text-secondary text-sm">
        {{ selectedTable ? '表为空' : '请选择业务表' }}
      </div>
      <div v-if="selectedTable && total > 0" class="px-4 py-ax-sm border-t border-outline-variant flex justify-between text-[11px] text-secondary">
        <span>{{ total }} 行</span>
        <div class="flex gap-ax-sm">
          <AxButton variant="ghost"  size="lg" :disabled="page<=1" @click="page--;fetchData()">上一页</AxButton>
          <span class="py-1">{{ page }} / {{ Math.ceil(total/size) || 1 }}</span>
          <AxButton variant="ghost"  size="lg" :disabled="page>=Math.ceil(total/size)" @click="page++;fetchData()">下一页</AxButton>
        </div>
      </div>
    </div>
  </div>
</template>